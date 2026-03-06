# JavaScript Coding Guide

Coding standards for JavaScript code. Following these rules reduces bugs, improves maintainability, and minimizes issues found in code reviews.

> **Prefer TypeScript for new projects.** This guide is for JavaScript-only codebases or mixed environments. See `CODING_GUIDE_TS.md` for TypeScript-specific patterns.

---

## 1. Project Setup

### 1.1 Use ESLint with Strict Rules

```jsonc
// .eslintrc.json (key rules)
{
  "env": { "es2022": true, "node": true },
  "parserOptions": { "ecmaVersion": 2022, "sourceType": "module" },
  "rules": {
    "eqeqeq": ["error", "always"],
    "no-var": "error",
    "prefer-const": "error",
    "no-unused-vars": ["error", { "argsIgnorePattern": "^_" }],
    "no-implicit-globals": "error",
    "no-floating-decimal": "error",
    "curly": ["error", "all"],
    "no-throw-literal": "error"
  }
}
```

### 1.2 Use ES Modules

```javascript
// BAD: CommonJS
const express = require("express");
module.exports = { startServer };

// GOOD: ES modules
import express from "express";
export { startServer };
```

---

## 2. Type Safety Without TypeScript

### 2.1 Use JSDoc for Type Annotations

```javascript
/**
 * @param {string} id - Work item identifier
 * @param {{ title: string, priority: number }} options
 * @returns {Promise<{ success: boolean, data: object }>}
 */
async function processItem(id, options) {
  // ...
}

/**
 * @typedef {Object} WorkItem
 * @property {string} id
 * @property {string} title
 * @property {number} priority
 * @property {Record<string, unknown>} data
 */

/** @type {WorkItem[]} */
const queue = [];
```

### 2.2 Always Use Strict Equality

```javascript
// BAD: Loose equality — surprising coercion
if (status == "0") { ... }     // true when status is 0 (number)
if (value == null) { ... }     // true for both null and undefined

// GOOD: Strict equality
if (status === "0") { ... }
if (value === null || value === undefined) { ... }
// Or for the null/undefined check specifically:
if (value == null) { ... }     // This is the ONE acceptable use of ==
```

### 2.3 Validate at Boundaries

Without TypeScript's compiler, runtime validation is critical.

```javascript
/**
 * @param {unknown} body
 * @returns {WorkItem}
 */
function parseWorkItem(body) {
  if (typeof body !== "object" || body === null) {
    throw new ValidationError("Body must be an object");
  }
  if (typeof body.id !== "string" || body.id.length === 0) {
    throw new ValidationError("id is required and must be a non-empty string");
  }
  if (typeof body.priority !== "number" || body.priority < 0 || body.priority > 10) {
    throw new ValidationError("priority must be a number between 0 and 10");
  }
  return { id: body.id, title: body.title ?? "", priority: body.priority, data: body.data ?? {} };
}
```

### 2.4 Use Constants Instead of Magic Values

```javascript
// BAD: Magic strings and numbers
if (status === "in_progress") {
  setTimeout(retry, 30000);
}

// GOOD: Named constants
const Status = Object.freeze({
  PENDING: "pending",
  IN_PROGRESS: "in_progress",
  COMPLETED: "completed",
});

const DEFAULT_TIMEOUT_MS = 30_000;

if (status === Status.IN_PROGRESS) {
  setTimeout(retry, DEFAULT_TIMEOUT_MS);
}
```

---

## 3. Error Handling

### 3.1 Never Swallow Errors

```javascript
// BAD: Silent failure
try {
  await fetchData();
} catch (e) {
  // nothing
}

// GOOD: Handle or re-throw
try {
  await fetchData();
} catch (e) {
  logger.error("Failed to fetch data", { error: e });
  throw new AppError("Data fetch failed", { cause: e });
}
```

### 3.2 Use Custom Error Classes

```javascript
class AppError extends Error {
  /**
   * @param {string} message
   * @param {string} code
   * @param {ErrorOptions} [options]
   */
  constructor(message, code = "UNKNOWN", options) {
    super(message, options);
    this.name = "AppError";
    this.code = code;
  }
}

class ValidationError extends AppError {
  constructor(message, options) {
    super(message, "VALIDATION_ERROR", options);
    this.name = "ValidationError";
  }
}

class NotFoundError extends AppError {
  constructor(resource, id) {
    super(`${resource} '${id}' not found`, "NOT_FOUND");
    this.name = "NotFoundError";
  }
}
```

### 3.3 Use `cause` for Error Chaining

```javascript
try {
  const data = JSON.parse(rawInput);
} catch (e) {
  throw new ValidationError("Invalid JSON input", { cause: e });
}
```

### 3.4 Handle Promise Rejections

```javascript
// BAD: Unhandled rejection
fetchData().then((data) => process(data));

// GOOD: async/await with try/catch
try {
  const data = await fetchData();
  await process(data);
} catch (e) {
  logger.error("Pipeline failed", { error: e });
}
```

---

## 4. Async Patterns

### 4.1 Prefer async/await Over .then() Chains

```javascript
// BAD: Nested .then() chains
function processItem(id) {
  return fetchItem(id)
    .then((item) => validate(item))
    .then((valid) => transform(valid))
    .then((result) => save(result))
    .catch((e) => handleError(e));
}

// GOOD: async/await
async function processItem(id) {
  const item = await fetchItem(id);
  const valid = await validate(item);
  const result = await transform(valid);
  return save(result);
}
```

### 4.2 Use Promise.all for Independent Operations

```javascript
// BAD: Sequential when order doesn't matter
const users = await fetchUsers();
const orders = await fetchOrders();
const products = await fetchProducts();

// GOOD: Parallel
const [users, orders, products] = await Promise.all([
  fetchUsers(),
  fetchOrders(),
  fetchProducts(),
]);
```

### 4.3 Use Promise.allSettled When Partial Failure Is Acceptable

```javascript
const results = await Promise.allSettled([
  notifySlack(message),
  notifyEmail(message),
  notifyWebhook(message),
]);

const failures = results.filter((r) => r.status === "rejected");
if (failures.length > 0) {
  logger.warn(`${failures.length} notifications failed`);
}
```

### 4.4 Never Block the Event Loop

```javascript
// BAD: Synchronous heavy computation blocks everything
function hashPasswords(passwords) {
  return passwords.map((p) => hashSync(p)); // Blocks!
}

// GOOD: Offload to worker or use async version
async function hashPasswords(passwords) {
  return Promise.all(passwords.map((p) => hashAsync(p)));
}
```

---

## 5. Module Organization

### 5.1 Use Named Exports

```javascript
// BAD: Default exports — harder to refactor, inconsistent naming
export default class UserService { ... }

// GOOD: Named exports
export class UserService { ... }
export function createUser(data) { ... }
```

### 5.2 Keep Side Effects Out of Module Scope

```javascript
// BAD: Side effect on import
const db = new Database(process.env.DB_URL); // Runs on import!
export function query(sql) { return db.query(sql); }

// GOOD: Explicit initialization
let db = null;

export function init(url) {
  db = new Database(url);
}

export function query(sql) {
  if (!db) throw new Error("Database not initialized — call init() first");
  return db.query(sql);
}
```

### 5.3 Keep Functions Short (< 50 lines)

```javascript
// BAD: 200-line function
function runWorkflow() {
  // ... 200 lines of initialization
  // ... 200 lines of main loop
  // ... 100 lines of cleanup
}

// GOOD: Composed of small functions
function runWorkflow() {
  const state = initializeWorkflow();
  const result = executeMainLoop(state);
  cleanupWorkflow(state);
  return result;
}
```

---

## 6. Immutability

### 6.1 Prefer `const` and Object.freeze

```javascript
// BAD: Mutable bindings
let count = 0;
var items = [1, 2, 3];

// GOOD: Immutable by default
const count = 0;
const items = Object.freeze([1, 2, 3]);

const Config = Object.freeze({
  host: "localhost",
  port: 8000,
});
```

### 6.2 Don't Mutate Function Arguments

```javascript
// BAD: Mutates the input
function addDefaults(config) {
  config.timeout = config.timeout ?? 30000; // Mutates caller's object!
  return config;
}

// GOOD: Return a new object
function addDefaults(config) {
  return { timeout: 30000, ...config };
}
```

---

## 7. Logging

### 7.1 Never Use console.log in Production Code

```javascript
// BAD: Unstructured, no levels, can't filter
console.log("Processing item", itemId);
console.log("DEBUG:", JSON.stringify(state));

// GOOD: Structured logger with levels (e.g., pino, winston)
import { logger } from "./logger.js";

logger.info("Processing item", { itemId });
logger.debug("Current state", { state });
logger.error("Processing failed", { itemId, error });
```

### 7.2 Use Structured Logging

```javascript
// BAD: String interpolation — hard to search/filter
logger.info(`User ${userId} created order ${orderId} for $${amount}`);

// GOOD: Structured fields — searchable, parseable
logger.info("Order created", { userId, orderId, amount });
```

---

## 8. Testing

### 8.1 Use describe/it Structure

```javascript
describe("WorkQueue", () => {
  describe("push", () => {
    it("adds item with correct priority", () => {
      const queue = new WorkQueue();
      queue.push({ id: "1", priority: 3 });
      expect(queue.size).toBe(1);
    });

    it("rejects duplicate IDs", () => {
      const queue = new WorkQueue();
      queue.push({ id: "1", priority: 3 });
      expect(() => queue.push({ id: "1", priority: 5 })).toThrow("Duplicate ID");
    });
  });
});
```

### 8.2 Mock at Boundaries, Not Internals

```javascript
// BAD: Mocking internal implementation details
jest.spyOn(service, "_processInternal");

// GOOD: Mock external dependencies
const mockFetch = jest.fn().mockResolvedValue({ ok: true, json: () => ({}) });
const service = new ApiService(mockFetch);
```

### 8.3 Test Error Conditions

```javascript
it("throws on invalid input", () => {
  expect(() => parseWorkItem(null)).toThrow(ValidationError);
  expect(() => parseWorkItem({ id: "" })).toThrow("non-empty string");
});

it("handles async failures", async () => {
  mockFetch.mockRejectedValue(new Error("Network error"));
  await expect(service.fetchItem("1")).rejects.toThrow("Network error");
});
```

---

## 9. Security

### 9.1 Never Interpolate User Input into HTML

```javascript
// BAD: XSS vulnerability
element.innerHTML = `<p>Hello, ${userName}</p>`;

// GOOD: Use textContent
element.textContent = `Hello, ${userName}`;

// Or with a framework (React auto-escapes)
return <p>Hello, {userName}</p>;
```

### 9.2 Validate and Sanitize at Boundaries

```javascript
// BAD: Trusts query parameters
app.get("/users", (req, res) => {
  const limit = req.query.limit;
  db.query(`SELECT * FROM users LIMIT ${limit}`); // SQL injection!
});

// GOOD: Validate and parameterize
app.get("/users", (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit ?? "20", 10), 1), 100);
  db.query("SELECT * FROM users LIMIT $1", [limit]);
});
```

### 9.3 Never Log Secrets

```javascript
// BAD
logger.debug("Connecting with token", { token: apiToken });

// GOOD
logger.debug("Connecting with token", { token: apiToken.slice(0, 8) + "..." });
```

### 9.4 Avoid eval and Dynamic Code Execution

```javascript
// BAD: eval is a security and maintenance nightmare
const result = eval(userExpression);

// BAD: Function constructor is eval in disguise
const fn = new Function("x", userCode);

// GOOD: Use a safe parser or whitelist approach
const result = safeEvaluate(userExpression, allowedContext);
```

---

## 10. Common JavaScript Pitfalls

### 10.1 Avoid `var` — Use `const` and `let`

```javascript
// BAD: var is function-scoped and hoisted
for (var i = 0; i < 5; i++) {
  setTimeout(() => console.log(i), 100); // Prints 5, 5, 5, 5, 5
}

// GOOD: let is block-scoped
for (let i = 0; i < 5; i++) {
  setTimeout(() => console.log(i), 100); // Prints 0, 1, 2, 3, 4
}
```

### 10.2 Watch for Truthiness Traps

```javascript
// BAD: Falsy values cause bugs
function getPort(config) {
  return config.port || 3000; // 0 is a valid port but falsy!
}

// GOOD: Nullish coalescing
function getPort(config) {
  return config.port ?? 3000; // Only falls back on null/undefined
}
```

### 10.3 Use Optional Chaining

```javascript
// BAD: Verbose null checks
const city = user && user.address && user.address.city;

// GOOD: Optional chaining
const city = user?.address?.city;
```

### 10.4 Use Structured Clone for Deep Copies

```javascript
// BAD: JSON round-trip loses dates, undefined, functions
const copy = JSON.parse(JSON.stringify(original));

// GOOD: structuredClone (available in Node 17+, all modern browsers)
const copy = structuredClone(original);
```

---

## Checklist Before Submitting Code

- [ ] No `var` — use `const` and `let`
- [ ] `===` used everywhere (except intentional `== null` checks)
- [ ] JSDoc annotations on all public functions
- [ ] No `console.log` — use structured logger
- [ ] All async errors handled (no unhandled rejections)
- [ ] Promises not left floating (awaited or returned)
- [ ] No mutation of function arguments
- [ ] External input validated at boundaries
- [ ] Named exports used (no default exports)
- [ ] No side effects at module scope
- [ ] No `eval` or `new Function`
- [ ] Tests cover critical paths and error conditions

---

## Quick Reference

| Anti-Pattern | Fix |
|--------------|-----|
| `var` | `const` or `let` |
| `==` | `===` (except `== null`) |
| `console.log` | Structured logger with levels |
| `.then().then().catch()` | `async/await` with `try/catch` |
| `catch (e) {}` empty | Log with context, re-throw or handle |
| `value \|\| default` for 0/empty | `value ?? default` (nullish coalescing) |
| `a && a.b && a.b.c` | `a?.b?.c` (optional chaining) |
| Sequential independent awaits | `Promise.all([...])` |
| `export default` | Named exports |
| `element.innerHTML = userInput` | `textContent` or framework escaping |
| `eval(userInput)` | Safe parser or whitelist |
| `JSON.parse(JSON.stringify(x))` | `structuredClone(x)` |
