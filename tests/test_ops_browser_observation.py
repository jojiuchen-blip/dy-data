"""A real, labelled browser observation must supply the missing restart signal."""

from datetime import UTC, datetime, timedelta
import json
import os
import socket
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import ComponentHeartbeat, JobRun, OpsCommand
from apps.ops_agent.docker_api import DockerAPI, DockerAPIError, GuardrailViolation
from test_ops_agent import _agent, _seed_command, _seed_heartbeat, factory  # noqa: F401


NOW = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
CONTAINER_ID = "a" * 64
LABELS = {"com.docker.compose.project": "synthetic", "com.docker.compose.service": "browser"}


def _inspect(*, started=None, health="healthy", running=True):
    started = started or NOW - timedelta(seconds=20)
    return {
        "Id": CONTAINER_ID,
        "Config": {"Labels": dict(LABELS), "Env": ["SECRET=DO_NOT_EXPORT"]},
        "State": {"Status": "running" if running else "exited", "Running": running,
                  "StartedAt": started.isoformat().replace("+00:00", "Z"),
                  "Health": {"Status": health, "Log": [{
                      "Start": (NOW-timedelta(seconds=3)).isoformat(),
                      "End": (NOW-timedelta(seconds=2)).isoformat(), "ExitCode": 0,
                      "Output": "DO_NOT_EXPORT_HEALTH_OUTPUT",
                  }]}},
    }


class Transport:
    def __init__(self, payload=None, *, rows=None, clock=None, advance=None):
        self.payload = _inspect() if payload is None else payload
        self.rows = [{"Id": CONTAINER_ID, "Labels": LABELS}] if rows is None else rows
        self.requests = []
        self.clock = clock
        self.advance = advance or {}

    def request(self, method, path, *, timeout=None):
        self.requests.append((method, path, timeout))
        if self.clock is not None:
            self.clock[0] += self.advance.get(len(self.requests), 0)
        value = self.rows if "/containers/json?" in path else self.payload
        if isinstance(value, Exception):
            raise value
        return 200, json.dumps(value).encode()


def _api(transport, *, monotonic=None):
    return DockerAPI(transport=transport, compose_project="synthetic", clock=lambda: NOW,
                     monotonic=monotonic)


def test_browser_inspect_exports_only_real_sanitized_facts():
    transport = Transport()
    observation = _api(transport).observe_browser()
    assert observation.container_id == CONTAINER_ID
    assert observation.started_at == NOW - timedelta(seconds=20)
    assert observation.observed_at == NOW and observation.status == "healthy"
    assert observation.health_checked_at == NOW - timedelta(seconds=2)
    assert "DO_NOT_EXPORT" not in repr(observation)
    assert [method for method, _, _ in transport.requests] == ["GET", "GET"]
    assert transport.requests[-1][1] == f"/v1.45/containers/{CONTAINER_ID}/json"


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(Id="other-container"),
    lambda p: p["Config"]["Labels"].update({"com.docker.compose.project": "other"}),
    lambda p: p["Config"]["Labels"].update({"com.docker.compose.service": "worker"}),
    lambda p: p["State"].pop("Health"),
    lambda p: p["State"].update(Running="true"),
    lambda p: p["State"].update(StartedAt="0001-01-01T00:00:00Z"),
    lambda p: p["State"].update(StartedAt="not-a-date"),
    lambda p: p["State"].update(StartedAt=(NOW+timedelta(seconds=1)).isoformat()),
    lambda p: p["State"]["Health"].update(Status="unknown"),
    lambda p: p["State"]["Health"].update(Log=[]),
    lambda p: p["State"]["Health"]["Log"][0].update(End=(NOW-timedelta(minutes=3)).isoformat()),
    lambda p: p["State"]["Health"]["Log"][0].update(End=(NOW+timedelta(seconds=1)).isoformat()),
    lambda p: p["State"]["Health"]["Log"][0].update(Start=(NOW-timedelta(minutes=3)).isoformat()),
    lambda p: p["State"]["Health"]["Log"][0].update(ExitCode=1),
])
def test_invalid_or_stale_browser_facts_fail_closed(mutate):
    payload = _inspect()
    mutate(payload)
    with pytest.raises((DockerAPIError, GuardrailViolation)):
        _api(Transport(payload)).observe_browser()


@pytest.mark.parametrize("rows", [[], [{"Id":"a","Labels":LABELS},{"Id":"b","Labels":LABELS}]])
def test_browser_observer_requires_exactly_one_labelled_target(rows):
    transport = Transport(rows=rows)
    with pytest.raises(GuardrailViolation):
        _api(transport).observe_browser()
    assert len(transport.requests) == 1


def test_nanosecond_start_identity_and_stopped_state_are_not_invented():
    payload = _inspect(running=False)
    payload["State"]["StartedAt"] = "2026-10-31T07:59:40.123456789Z"
    observation = _api(Transport(payload)).observe_browser()
    assert observation.status == "stopped"
    assert observation.started_at == datetime(2026,10,31,7,59,40,123456,tzinfo=UTC)


def test_observer_serial_requests_share_one_remaining_budget():
    clock = [0.0]
    transport = Transport(clock=clock, advance={1: 8.0})
    _api(transport, monotonic=lambda: clock[0]).observe_browser(timeout_seconds=10)
    assert transport.requests[0][2] == 10
    assert transport.requests[1][2] == 2


@pytest.mark.parametrize("budget", [0,-1,21,float("inf"),float("nan"),True,"10"])
def test_invalid_observer_budget_makes_no_docker_request(budget):
    transport=Transport()
    with pytest.raises(GuardrailViolation):
        _api(transport).observe_browser(timeout_seconds=budget)
    assert transport.requests==[]


@pytest.mark.parametrize("failure_stage", ["lookup","inspect"])
def test_observer_transport_timeout_returns_only_a_safe_error(failure_stage):
    transport=Transport(payload=TimeoutError("DO_NOT_EXPORT"))
    if failure_stage=="lookup":
        transport.rows=TimeoutError("DO_NOT_EXPORT")
    with pytest.raises(DockerAPIError) as error:
        _api(transport).observe_browser()
    assert "DO_NOT_EXPORT" not in str(error.value)


def test_observer_budget_exhausted_by_lookup_never_starts_inspect():
    clock=[0.0]
    transport=Transport(clock=clock,advance={1:11})
    with pytest.raises(DockerAPIError,match="timed out"):
        _api(transport,monotonic=lambda:clock[0]).observe_browser(timeout_seconds=10)
    assert len(transport.requests)==1


def test_observer_rejects_noncanonical_lookup_id_before_inspect():
    transport=Transport(rows=[{"Id":"..","Labels":LABELS}])
    with pytest.raises(GuardrailViolation,match="canonical"):
        _api(transport).observe_browser()
    assert len(transport.requests)==1


def test_nanosecond_start_token_keeps_actual_start_identities_distinct():
    first=_inspect()
    first["State"]["StartedAt"]="2026-10-31T07:59:40.123456001Z"
    second=_inspect()
    second["State"]["StartedAt"]="2026-10-31T07:59:40.123456999Z"
    a=_api(Transport(first)).observe_browser()
    b=_api(Transport(second)).observe_browser()
    assert a.started_at==b.started_at and a.instance_id!=b.instance_id


class BrowserDocker:
    """No browser database writer: all facts come from the Docker observer."""
    def __init__(self, clock, *, health="healthy", stale=False):
        self.clock = clock
        self.health = health
        self.started = NOW-timedelta(hours=1)
        self.stale = stale
        self.restart_calls = []
        self.observe_calls = []

    def resolve_target(self, target):
        from apps.ops_agent.docker_api import ContainerRef
        assert target == "browser"
        return [ContainerRef(CONTAINER_ID, "browser")]

    def restart(self, container, *, grace_seconds):
        self.restart_calls.append((container.container_id,grace_seconds))
        self.clock[0] += timedelta(seconds=2)
        if not self.stale:
            self.started = self.clock[0]-timedelta(seconds=1)

    def observe_browser(self, *, timeout_seconds=20):
        from apps.ops_agent.docker_api import BrowserObservation
        self.observe_calls.append(timeout_seconds)
        return BrowserObservation(container_id=CONTAINER_ID, started_at=self.started,
            observed_at=self.clock[0], health_checked_at=self.clock[0], status=self.health)


def _browser_agent(factory, docker, clock):
    return _agent(factory,docker,NOW,clock=lambda:clock[0],heartbeat_timeout_seconds=5,
        heartbeat_poll_seconds=1,monotonic=lambda:(clock[0]-NOW).total_seconds(),
        sleep=lambda seconds:clock.__setitem__(0,clock[0]+timedelta(seconds=seconds)))


def test_browser_restart_gets_real_heartbeat_without_browser_db_credentials(factory):
    command_id = _seed_command(factory, now=NOW, target="browser")
    clock=[NOW]
    docker=BrowserDocker(clock)
    result=_browser_agent(factory,docker,clock).run_once()
    assert result.status == "success" and result.result_code == "restart_confirmed"
    assert docker.restart_calls == [(CONTAINER_ID,30)]
    with factory() as session:
        row=session.scalar(select(ComponentHeartbeat).where(ComponentHeartbeat.component_type=="browser"))
        assert row.status == "healthy" and row.started_at.replace(tzinfo=UTC)>NOW
        assert row.activity_json["observer"]=="ops_agent" and row.activity_json["source"]=="docker_inspect"
        assert row.current_job_id is row.rss_bytes is row.cpu_percent is row.queue_depth is None
        assert session.get(OpsCommand,command_id).status=="success"


@pytest.mark.parametrize("health,stale", [("starting",False),("unhealthy",False),("healthy",True)])
def test_browser_starting_unhealthy_or_old_instance_cannot_complete_restart(factory,health,stale):
    _seed_command(factory,now=NOW,target="browser")
    clock=[NOW]
    result=_browser_agent(factory,BrowserDocker(clock,health=health,stale=stale),clock).run_once()
    assert result.status=="failed" and result.result_code=="replacement_heartbeat_timeout"


def test_idle_observer_does_not_mask_another_instance_export_activity(factory):
    _seed_heartbeat(factory,component_type="browser",instance_id="export-source",now=NOW,
        started_at=NOW-timedelta(hours=1),activity={"export_active":True})
    clock=[NOW+timedelta(seconds=2)]
    docker=BrowserDocker(clock)
    agent=_browser_agent(factory,docker,clock)
    assert agent.run_once() is None
    _seed_command(factory,now=clock[0],target="browser")
    result=agent.run_once()
    assert result.result_code=="browser_export_active" and docker.restart_calls==[]


def test_browser_observation_lease_budget_is_explicit_without_changing_worker_budget(factory):
    clock=[NOW]
    agent=_browser_agent(factory,BrowserDocker(clock),clock)
    assert agent._claim_lease_seconds("browser")==120+20+30+15+5+1+20+1
    assert agent._remaining_lease_seconds("browser",include_lookup=False)==30+15+5+1+20+1
    assert agent._claim_lease_seconds("worker")==120+20+300+15+5+1+1


def test_owner_replaced_during_observation_cannot_mark_command_success(factory):
    command_id=_seed_command(factory,now=NOW,target="browser")
    clock=[NOW]
    docker=BrowserDocker(clock)
    original=docker.observe_browser
    def fenced_observation(**kwargs):
        observation=original(**kwargs)
        with factory() as session:
            command=session.get(OpsCommand,command_id)
            command.claimed_by="different-owner"
            command.lease_epoch+=1
            session.commit()
        return observation
    docker.observe_browser=fenced_observation
    with pytest.raises(RuntimeError,match="lease"):
        _browser_agent(factory,docker,clock).run_once()
    with factory() as session:
        command=session.get(OpsCommand,command_id)
        assert command.status=="running" and command.claimed_by=="different-owner"


def test_export_beginning_during_second_lookup_blocks_restart(factory):
    _seed_command(factory,now=NOW,target="browser")
    clock=[NOW]
    docker=BrowserDocker(clock)
    original=docker.resolve_target
    calls=[]
    def resolve(target):
        calls.append(target)
        if len(calls)==2:
            _seed_heartbeat(factory,component_type="browser",instance_id="concurrent-export",
                now=NOW,started_at=NOW-timedelta(hours=1),activity={"state":"exporting"})
        return original(target)
    docker.resolve_target=resolve
    result=_browser_agent(factory,docker,clock).run_once()
    assert result.result_code=="browser_export_active" and docker.restart_calls==[]


def test_database_wait_consumes_observation_budget_before_writing_or_confirming(factory):
    _seed_command(factory,now=NOW,target="browser")
    clock=[NOW]
    engine=factory.kw["bind"]
    exhausted=[False]
    def delay(_conn,_cursor,statement,_parameters,_context,_many):
        if not exhausted[0] and statement.lstrip().upper().startswith("SELECT COMPONENT_HEARTBEATS."):
            clock[0]+=timedelta(seconds=6)
            exhausted[0]=True
    # Install only after the pre-restart lookup, so the exhausted phase is the
    # observer's actual DB read rather than the old activity/before signal.
    docker=BrowserDocker(clock)
    original=docker.restart
    def restart(container,**kwargs):
        original(container,**kwargs)
        event.listen(engine,"before_cursor_execute",delay)
    docker.restart=restart
    try:
        result=_browser_agent(factory,docker,clock).run_once()
    finally:
        event.remove(engine,"before_cursor_execute",delay)
    assert exhausted[0] and result.result_code=="replacement_heartbeat_timeout"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ComponentHeartbeat).where(
            ComponentHeartbeat.component_type=="browser"))==0


def test_commit_hook_cannot_add_writes_after_observation_is_sealed(factory):
    clock=[NOW]
    agent=_browser_agent(factory,BrowserDocker(clock),clock)
    def add_extra(session):
        if any(isinstance(x,ComponentHeartbeat) and x.component_type=="browser" for x in session.identity_map.values()):
            session.add(ComponentHeartbeat(component_instance_id="unexpected-commit-row",
                component_type="browser",status="healthy",last_heartbeat_at=NOW))
    event.listen(Session,"before_commit",add_extra)
    try:
        assert agent._observe_browser_once(timeout_seconds=5) is None
    finally:
        event.remove(Session,"before_commit",add_extra)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ComponentHeartbeat))==0


@pytest.fixture
def postgres_observer_factory():
    url=os.getenv("DYDATA_FINANCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("dedicated local PostgreSQL URL not configured")
    parsed=make_url(url)
    assert parsed.host in {"localhost","127.0.0.1"} and parsed.database.endswith("_test")
    schema="ops_observer_"+uuid4().hex
    admin=create_engine(url,hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(url,hide_parameters=True,connect_args={"options":
        f"-c search_path={schema} -c statement_timeout=80 -c lock_timeout=30"})
    setup=create_engine(url,hide_parameters=True,connect_args={"options":
        f"-c search_path={schema} -c statement_timeout=3000 -c lock_timeout=1000"})
    try:
        # This budget-only fixture needs the actual heartbeat table plus its
        # immediate job FK target, not the whole financial/application schema.
        JobRun.__table__.create(setup)
        ComponentHeartbeat.__table__.create(setup)
        yield sessionmaker(bind=engine,autoflush=False),engine
    finally:
        engine.dispose()
        setup.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_postgres_locked_observation_times_out_without_advancing_heartbeat(postgres_observer_factory):
    factory,engine=postgres_observer_factory
    clock=[NOW]
    agent=_browser_agent(factory,BrowserDocker(clock),clock)
    assert agent._observe_browser_once(timeout_seconds=5) is not None
    with factory() as session:
        identity=session.scalar(select(ComponentHeartbeat.component_instance_id))
    with engine.connect() as blocker:
        transaction=blocker.begin()
        blocker.execute(text("SELECT component_instance_id FROM component_heartbeats FOR UPDATE"))
        clock[0]+=timedelta(seconds=1)
        assert agent._observe_browser_once(timeout_seconds=5) is None
        transaction.rollback()
    with factory() as session:
        row=session.get(ComponentHeartbeat,identity)
        assert row.last_heartbeat_at==NOW


def test_postgres_deferred_trigger_runs_inside_remaining_statement_budget(postgres_observer_factory):
    factory,engine=postgres_observer_factory
    with engine.begin() as connection:
        connection.execute(text("CREATE FUNCTION slow_observation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.2); RETURN NEW; END $$"))
        connection.execute(text("CREATE CONSTRAINT TRIGGER slow_observation AFTER INSERT ON component_heartbeats DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION slow_observation()"))
    clock=[NOW]
    agent=_agent(factory,BrowserDocker(clock),NOW,clock=lambda:clock[0])
    assert agent._observe_browser_once(timeout_seconds=.05) is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ComponentHeartbeat))==0


def test_postgres_observation_preserves_existing_smaller_sql_limits(postgres_observer_factory):
    factory,engine=postgres_observer_factory
    seen=[]
    def capture(_connection,cursor,statement,_parameters,_context,_many):
        if statement.startswith("SET CONSTRAINTS"):
            cursor.execute("SELECT name,setting FROM pg_settings WHERE name IN ('statement_timeout','lock_timeout')")
            seen.append(dict(cursor.fetchall()))
    event.listen(engine,"before_cursor_execute",capture)
    try:
        clock=[NOW]
        assert _browser_agent(factory,BrowserDocker(clock),clock)._observe_browser_once(timeout_seconds=5) is not None
    finally:
        event.remove(engine,"before_cursor_execute",capture)
    assert seen and all(0<int(x["statement_timeout"])<=80 and 0<int(x["lock_timeout"])<=30 for x in seen)


def _process_agent():
    from apps.ops_agent.main import OpsAgent
    return OpsAgent(factory=sessionmaker(),docker=object(),instance_id="synthetic-process-test")


def _child_program(monkeypatch, program):
    """Explicit test transport: production argv remains a fixed internal action."""
    from apps.ops_agent import main as service
    original=subprocess.Popen
    children=[]
    def launch(arguments,**kwargs):
        assert arguments[:4]==[sys.executable,"-m","apps.ops_agent.main","--observe-browser-once"]
        assert len(arguments)==5 and float(arguments[4])>time.monotonic()
        assert kwargs.get("shell",False) is False and kwargs["stderr"]==subprocess.DEVNULL
        process=original([sys.executable,"-c",program],**kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(service.subprocess,"Popen",launch)
    return children


def _valid_reply():
    now=datetime.now(UTC)
    return {"container_id":CONTAINER_ID,"started_at":(now-timedelta(seconds=5)).isoformat(),
        "observed_at":now.isoformat(),"health_checked_at":(now-timedelta(seconds=1)).isoformat(),
        "status":"healthy","started_at_raw":(now-timedelta(seconds=5)).isoformat()}


def test_fixed_child_reply_is_accepted_only_after_successful_exit(monkeypatch):
    reply=_valid_reply()
    children=_child_program(monkeypatch,"print("+repr(json.dumps(reply))+")")
    result=_process_agent()._observe_browser_subprocess(2)
    assert result is not None and result.container_id==CONTAINER_ID
    assert children[0].poll()==0


@pytest.mark.parametrize("program", [
    "print('{}')", "print('x'*5000)", "raise SystemExit(2)",
    "print('{not-json}')", "print('[]')",
])
def test_bad_oversized_or_nonzero_child_never_reports_success(monkeypatch,program):
    children=_child_program(monkeypatch,program)
    assert _process_agent()._observe_browser_subprocess(2) is None
    assert children[0].poll() is not None


@pytest.mark.parametrize("field,value",[("container_id","other"),("status",[]),("health_checked_at",None),
    ("started_at_raw","2026-10-31T00:00:00Z")])
def test_child_reply_invalid_real_facts_are_rejected(monkeypatch,field,value):
    payload=_valid_reply();payload[field]=value
    children=_child_program(monkeypatch,"print("+repr(json.dumps(payload))+")")
    assert _process_agent()._observe_browser_subprocess(2) is None
    assert children[0].poll() is not None


def test_child_early_valid_reply_cannot_leave_background_writes_after_timeout(monkeypatch,tmp_path):
    late=tmp_path/"late-write.txt"
    program="import time;from pathlib import Path;print("+repr(json.dumps(_valid_reply()))+",flush=True);time.sleep(3);Path("+repr(str(late))+").write_text('unexpected')"
    children=_child_program(monkeypatch,program)
    started=time.monotonic()
    assert _process_agent()._observe_browser_subprocess(.3) is None
    assert time.monotonic()-started<.8 and children[0].poll() is not None and not late.exists()


def test_real_child_slow_connection_pool_is_killed_and_reaped(monkeypatch,tmp_path):
    entered=tmp_path/"pool-entered.txt"
    late=tmp_path/"late-pool-write.txt"
    program="""from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
e=create_engine('sqlite://',poolclass=QueuePool,pool_size=1,max_overflow=0,pool_timeout=5)
with e.connect() as held:
 Path(ENTERED).write_text('entered')
 with e.connect(): Path(LATE).write_text('unexpected')
""".replace('ENTERED',repr(str(entered))).replace('LATE',repr(str(late)))
    children=_child_program(monkeypatch,program)
    started=time.monotonic()
    assert _process_agent()._observe_browser_subprocess(2) is None
    elapsed=time.monotonic()-started
    assert entered.exists() and not late.exists() and elapsed<2.6 and children[0].poll() is not None


def test_real_child_http_slow_drip_is_bounded_by_parent_deadline(monkeypatch):
    server=socket.socket()
    server.bind(('127.0.0.1',0));server.listen(1)
    port=server.getsockname()[1]
    accepted=Event()
    def serve():
        connection=None
        try:
            connection,_=server.accept()
            connection.recv(4096)
            connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n')
            accepted.set()
            for _ in range(1000):
                connection.sendall(b'x');time.sleep(.01)
        except OSError:
            pass
        finally:
            if connection is not None:
                connection.close()
    thread=Thread(target=serve,daemon=True);thread.start()
    program="""import http.client
from apps.ops_agent import docker_api
docker_api._UnixSocketConnection=lambda path,timeout:http.client.HTTPConnection('127.0.0.1',PORT,timeout=timeout)
docker_api.UnixSocketDockerTransport('/synthetic.sock').request('GET','/v1.45/containers/synthetic/json',timeout=.05)
""".replace('PORT',str(port))
    children=_child_program(monkeypatch,program)
    started=time.monotonic()
    try:
        assert _process_agent()._observe_browser_subprocess(2) is None
        elapsed=time.monotonic()-started
        assert accepted.is_set() and elapsed<2.6 and children[0].poll() is not None, (accepted.is_set(),elapsed,children[0].poll())
    finally:
        server.close();thread.join(timeout=2)


def test_idle_observation_cadence_is_bounded_without_delaying_commands():
    from apps.ops_agent.main import OpsAgent
    clock=[0.0];calls=[]
    agent=OpsAgent(factory=sessionmaker(),docker=object(),instance_id="cadence",monotonic=lambda:clock[0],
        browser_observer=lambda budget:calls.append(budget))
    agent._claim_next=lambda:None
    assert agent.run_once() is None
    clock[0]=20;assert agent.run_once() is None
    clock[0]=31;assert agent.run_once() is None
    assert calls==[20,20]
