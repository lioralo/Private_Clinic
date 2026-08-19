This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started (Local)

### 1) Configure environment
```bash
cp .env.example .env.local
```

### 2) Create the database + seed admin user
```bash
npm run db:migrate
npm run db:seed
```

### 3) Start the dev server
```bash
npm run dev
```

Open: http://localhost:3000

Login:
- username: `ADMIN_USERNAME` (default `admin`)
- password: `ADMIN_PASSWORD` (default `admin-password`)

## Testing

Unit/integration tests:
```bash
npm run test
```

E2E smoke tests (requires Playwright setup):
```bash
npm run e2e
```
