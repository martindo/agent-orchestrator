# TypeScript Coding Guide

Coding standards for TypeScript code. Following these rules reduces bugs, improves maintainability, and minimizes issues found in code reviews.

---

## 1. Project Setup

### 1.1 Use Strict Mode

```jsonc
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "forceConsistentCasingInFileNames": true,
    "exactOptionalPropertyTypes": true
  }
}
```

### 1.2 Use ESLint with TypeScript Rules

```jsonc
// .eslintrc.json (key rules)
{
  "rules": {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/no-floating-promises": "error",
    "@typescript-eslint/no-misused-promises": "error",
    "@typescript-eslint/strict-boolean-expressions": "warn"
  }
}
```

---

## 2. Type Safety

### 2.1 Never Use `any`

```typescript
// BAD: Defeats the purpose of TypeScript
function process(data: any): any {
  return data.items.map((i: any) => i.name);
}

// GOOD: Explicit types
interface Item {
  name: string;
  value: number;
}

function process(data: { items: Item[] }): string[] {
  return data.items.map((i) => i.name);
}

// If truly unknown, use `unknown` and narrow
function handleResponse(data: unknown): string {
  if (typeof data === "object" && data !== null && "message" in data) {
    return (data as { message: string }).message;
  }
  throw new Error("Unexpected response shape");
}
```

### 2.2 Use Type Inference Where Obvious

```typescript
// UNNECESSARY: Type is obvious from the right side
const name: string = "hello";
const items: number[] = [1, 2, 3];

// GOOD: Let TypeScript infer
const name = "hello";
const items = [1, 2, 3];

// DO annotate when types aren't obvious
const config: ServerConfig = loadConfig();
const result: ProcessResult = await engine.run(input);
```

### 2.3 Use Discriminated Unions for State Machines

```typescript
// BAD: Optional fields for every possible state
interface ApiResponse {
  status: string;
  data?: unknown;
  error?: string;
  retryAfter?: number;
}

// GOOD: Discriminated union — compiler enforces correctness
type ApiResponse =
  | { status: "success"; data: unknown }
  | { status: "error"; error: string }
  | { status: "rate_limited"; retryAfter: number };

function handle(response: ApiResponse) {
  switch (response.status) {
    case "success":
      return process(response.data);
    case "error":
      throw new Error(response.error);
    case "rate_limited":
      return retry(response.retryAfter);
  }
}
```

### 2.4 Use `as const` for Literal Types

```typescript
// BAD: Widened to string[]
const STATUSES = ["pending", "running", "done"];

// GOOD: Narrow literal types
const STATUSES = ["pending", "running", "done"] as const;
type Status = (typeof STATUSES)[number]; // "pending" | "running" | "done"
```

### 2.5 Prefer Interfaces for Objects, Types for Unions

```typescript
// Object shapes — use interface (extendable, better error messages)
interface WorkItem {
  id: string;
  title: string;
  priority: number;
}

// Unions, intersections, mapped types — use type
type Result = Success | Failure;
type Nullable<T> = T | null;
```

### 2.6 Use Zod for Runtime Validation at Boundaries

TypeScript types are erased at runtime. Validate at system boundaries.

```typescript
import { z } from "zod";

const WorkItemSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1).max(200),
  priority: z.number().int().min(0).max(10),
  data: z.record(z.unknown()).default({}),
});

type WorkItem = z.infer<typeof WorkItemSchema>;

// At API boundary
function handleRequest(body: unknown): WorkItem {
  return WorkItemSchema.parse(body); // Throws ZodError on invalid input
}
```

---

## 3. Error Handling

### 3.1 Never Swallow Errors

```typescript
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

```typescript
class AppError extends Error {
  constructor(
    message: string,
    public readonly code: string = "UNKNOWN",
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "AppError";
  }
}

class ValidationError extends AppError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "VALIDATION_ERROR", options);
    this.name = "ValidationError";
  }
}

class NotFoundError extends AppError {
  constructor(resource: string, id: string) {
    super(`${resource} '${id}' not found`, "NOT_FOUND");
    this.name = "NotFoundError";
  }
}
```

### 3.3 Use `cause` for Error Chaining

```typescript
try {
  const data = JSON.parse(rawInput);
} catch (e) {
  throw new ValidationError("Invalid JSON input", { cause: e });
}
```

### 3.4 Handle Promise Rejections

```typescript
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

```typescript
// BAD: Nested .then() chains
function processItem(id: string) {
  return fetchItem(id)
    .then((item) => validate(item))
    .then((valid) => transform(valid))
    .then((result) => save(result))
    .catch((e) => handleError(e));
}

// GOOD: async/await
async function processItem(id: string): Promise<SaveResult> {
  const item = await fetchItem(id);
  const valid = await validate(item);
  const result = await transform(valid);
  return save(result);
}
```

### 4.2 Use Promise.all for Independent Operations

```typescript
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

```typescript
const results = await Promise.allSettled([
  notifySlack(message),
  notifyEmail(message),
  notifyWebhook(message),
]);

const failures = results.filter(
  (r): r is PromiseRejectedResult => r.status === "rejected",
);
if (failures.length > 0) {
  logger.warn(`${failures.length} notifications failed`);
}
```

### 4.4 Never Block the Event Loop

```typescript
// BAD: Synchronous heavy computation blocks everything
function hashPasswords(passwords: string[]): string[] {
  return passwords.map((p) => hashSync(p)); // Blocks!
}

// GOOD: Offload to worker or use async version
async function hashPasswords(passwords: string[]): Promise<string[]> {
  return Promise.all(passwords.map((p) => hashAsync(p)));
}
```

---

## 5. Module Organization

### 5.1 Use Named Exports

```typescript
// BAD: Default exports — harder to refactor, inconsistent naming
export default class UserService { ... }

// GOOD: Named exports
export class UserService { ... }
export function createUser(data: CreateUserInput): User { ... }
```

### 5.2 Use Barrel Files Sparingly

```typescript
// src/services/index.ts
// GOOD: Re-export public API only
export { UserService } from "./user-service";
export { OrderService } from "./order-service";
export type { CreateUserInput, User } from "./types";

// BAD: Re-exporting everything — breaks tree shaking, circular deps
export * from "./user-service";
export * from "./order-service";
export * from "./internal-helpers"; // Internal leaks out!
```

### 5.3 Keep Side Effects Out of Module Scope

```typescript
// BAD: Side effect on import
const db = new Database(process.env.DB_URL!); // Runs on import!
export function query(sql: string) { return db.query(sql); }

// GOOD: Explicit initialization
let db: Database | null = null;

export function init(url: string): void {
  db = new Database(url);
}

export function query(sql: string) {
  if (!db) throw new Error("Database not initialized — call init() first");
  return db.query(sql);
}
```

---

## 6. Immutability

### 6.1 Prefer `const` and `readonly`

```typescript
// BAD: Mutable bindings
let count = 0;
let items = [1, 2, 3];

// GOOD: Immutable by default
const count = 0;
const items = [1, 2, 3] as const;

// For object properties
interface Config {
  readonly host: string;
  readonly port: number;
}
```

### 6.2 Don't Mutate Function Arguments

```typescript
// BAD: Mutates the input
function addDefaults(config: Record<string, unknown>) {
  config.timeout = config.timeout ?? 30000; // Mutates caller's object!
  return config;
}

// GOOD: Return a new object
function addDefaults(config: Record<string, unknown>) {
  return { timeout: 30000, ...config };
}
```

---

## 7. Logging

### 7.1 Never Use console.log in Production Code

```typescript
// BAD: Unstructured, no levels, can't filter
console.log("Processing item", itemId);
console.log("DEBUG:", JSON.stringify(state));

// GOOD: Structured logger with levels
import { logger } from "./logger";

logger.info("Processing item", { itemId });
logger.debug("Current state", { state });
logger.error("Processing failed", { itemId, error });
```

### 7.2 Use Structured Logging

```typescript
// BAD: String interpolation — hard to search/filter
logger.info(`User ${userId} created order ${orderId} for $${amount}`);

// GOOD: Structured fields — searchable, parseable
logger.info("Order created", { userId, orderId, amount });
```

---

## 8. Testing

### 8.1 Use describe/it Structure

```typescript
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

```typescript
// BAD: Mocking internal implementation details
jest.spyOn(service, "_processInternal");

// GOOD: Mock external dependencies
const mockFetch = jest.fn().mockResolvedValue({ ok: true, json: () => ({}) });
const service = new ApiService(mockFetch);
```

### 8.3 Use Type-Safe Mocks

```typescript
// BAD: Partial mock loses type safety
const mockDb = { query: jest.fn() } as any;

// GOOD: Type-safe mock
const mockDb: jest.Mocked<Database> = {
  query: jest.fn(),
  connect: jest.fn(),
  disconnect: jest.fn(),
};
```

---

## 9. Security

### 9.1 Never Interpolate User Input into HTML

```typescript
// BAD: XSS vulnerability
element.innerHTML = `<p>Hello, ${userName}</p>`;

// GOOD: Use textContent or a sanitizer
element.textContent = `Hello, ${userName}`;

// Or with a framework (React auto-escapes)
return <p>Hello, {userName}</p>;
```

### 9.2 Validate and Sanitize at Boundaries

```typescript
// BAD: Trusts query parameters
app.get("/users", (req, res) => {
  const limit = req.query.limit; // Could be anything!
  db.query(`SELECT * FROM users LIMIT ${limit}`); // SQL injection!
});

// GOOD: Validate and parameterize
app.get("/users", (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit ?? "20"), 1), 100);
  db.query("SELECT * FROM users LIMIT $1", [limit]);
});
```

### 9.3 Never Log Secrets

```typescript
// BAD
logger.debug("Connecting with token", { token: apiToken });

// GOOD
logger.debug("Connecting with token", { token: apiToken.slice(0, 8) + "..." });
```

---

## Checklist Before Submitting Code

- [ ] `strict: true` in tsconfig with no `any` types
- [ ] No `console.log` — use structured logger
- [ ] All async errors handled (no unhandled rejections)
- [ ] Promises not left floating (awaited or returned)
- [ ] No mutation of function arguments
- [ ] External input validated at boundaries (Zod or equivalent)
- [ ] Named exports used (no default exports)
- [ ] No side effects at module scope
- [ ] Discriminated unions used for state variants
- [ ] Tests cover critical paths and error conditions

---

## Quick Reference

| Anti-Pattern | Fix |
|--------------|-----|
| `any` type | Use `unknown` and narrow, or define proper types |
| `console.log` | Structured logger with levels |
| `.then().then().catch()` | `async/await` with `try/catch` |
| `catch (e) {}` empty | Log with context, re-throw or handle |
| Sequential independent awaits | `Promise.all([...])` |
| `export default` | Named exports |
| `element.innerHTML = userInput` | `textContent` or framework escaping |
| Mutable shared state | `const`, `readonly`, return new objects |
| String template SQL/HTML | Parameterized queries, framework escaping |
| `as any` in mocks | `jest.Mocked<T>` for type-safe mocks |
