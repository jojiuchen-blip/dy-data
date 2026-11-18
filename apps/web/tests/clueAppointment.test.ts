import assert from "node:assert/strict";
import test from "node:test";
import { toShanghaiAppointmentAt, toShanghaiAppointmentInput } from "../src/utils/clueAppointment.ts";

test("submits Beijing wall-clock appointments with an explicit timezone", () => {
  for (const timezone of ["UTC", "America/New_York", "Asia/Shanghai"]) {
    const previous = process.env.TZ;
    try {
      process.env.TZ = timezone;
      assert.equal(toShanghaiAppointmentAt("2026-11-19T00:30"), "2026-11-19T00:30:00+08:00");
      assert.equal(new Date(toShanghaiAppointmentAt("2026-11-19T00:30")!).toISOString(), "2026-11-18T16:30:00.000Z");
      assert.equal(toShanghaiAppointmentInput("2026-11-18T16:30:00Z"), "2026-11-19T00:30");
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  }
});

test("rejects missing, malformed and impossible dates without rolling them forward", () => {
  for (const value of ["", "2026-02-30T10:00", "2026-11-19T24:00", "2026-13-19T10:00", "2026-11-19", "2026-11-19T10:00Z"]) {
    assert.equal(toShanghaiAppointmentAt(value), null, value);
  }
  assert.equal(toShanghaiAppointmentAt("2028-02-29T10:00"), "2028-02-29T10:00:00+08:00");
  assert.equal(toShanghaiAppointmentInput(null), "");
  assert.equal(toShanghaiAppointmentInput("invalid"), "");
});
