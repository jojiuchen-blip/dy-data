#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const hostRoot = path.resolve(process.argv[2] || process.cwd());
const executionPlanPath = path.join(hostRoot, 'docs', 'plans', 'execution-plan.md');
const executionPlan = fs.readFileSync(executionPlanPath, 'utf8');
const currentPlanMatch = executionPlan.match(
  /^- 当前正式计划：.*?\]\((delivery-plans\/main-delivery-plan-[^)]+\.md)\)/mu,
);

if (!currentPlanMatch) {
  throw new Error('Unable to locate the current formal delivery plan in docs/plans/execution-plan.md.');
}

const relativePlanPath = currentPlanMatch[1].replaceAll('/', path.sep);
const deliveryPlansRoot = path.resolve(hostRoot, 'docs', 'plans', 'delivery-plans');
const planPath = path.resolve(hostRoot, 'docs', 'plans', relativePlanPath);
const deliveryPlansPrefix = `${deliveryPlansRoot}${path.sep}`;

if (!planPath.startsWith(deliveryPlansPrefix) || !/^main-delivery-plan-.+\.md$/u.test(path.basename(planPath))) {
  throw new Error(`Current formal delivery plan is outside the allowed directory: ${relativePlanPath}`);
}

if (!fs.existsSync(planPath)) {
  throw new Error(`Current formal delivery plan does not exist: ${relativePlanPath}`);
}

const now = new Date();
fs.utimesSync(planPath, now, now);
console.log(`Marked current formal delivery plan for deterministic governance selection: ${relativePlanPath}`);
