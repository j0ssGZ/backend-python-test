# AMS Solutions Backend Challenge

## Goal
Build a production-minded notification API using the existing
FastAPI project and infrastructure.

## Engineering principles
- Python 3.12.
- Clean code, SOLID and pragmatic hexagonal architecture.
- TDD with pytest.
- Type hints and Pydantic v2.
- Async HTTP integrations using httpx.
- Clear separation of domain, application and infrastructure.
- Explicit error handling and structured logging.
- Prefer simple, maintainable solutions.
- Avoid unnecessary dependencies and abstractions.

## Rules
- Inspect the repository before making changes.
- Preserve the provided API contracts.
- Do not modify the provider or load tests to make tests pass.
- Never hide failures or hardcode successful responses.
- Use environment variables for configuration.
- Keep tests deterministic.
- Run relevant tests after changes.
- Document architectural decisions and trade-offs.
- Maintain compatibility with the supplied Docker Compose.

## Workflow
1. Analyze requirements.
2. Propose an implementation plan.
3. Implement in small vertical slices.
4. Test each slice.
5. Run integration and load tests.
6. Review results and documentation.

## Communication
- Explain architecture and important trade-offs in Spanish.
- Write code, comments and documentation in English.
- Keep responses concise.
- Ask for approval before major architectural changes.
- Recommend cheaper models for straightforward tasks.

## Git Workflow
- Work directly on `main` in my personal fork.
- Never push to upstream or modify the original repository.
- Create atomic commits automatically whenever a coherent, independently verifiable unit of work is completed.
- Each commit must represent one logical change: a feature, bug fix, refactoring, test improvement or documentation update.
- Prefer small, focused commits over large batches of unrelated changes.
- Keep every intermediate commit buildable and independently verifiable; do not fabricate milestone history.
- Follow Conventional Commits: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`.
- Run relevant tests and checks before each commit. Never knowingly commit failing code unless explicitly authorized.
- Review `git status` and `git diff` before staging changes.
- Never include unrelated files, credentials, secrets or generated artifacts.
- Do not amend, squash, rebase or rewrite existing commits without explicit approval.
- Never push to origin without explicit approval.
- At the end of each milestone, summarize the commits created, tests executed and any outstanding work.
- Do not request approval for routine atomic commits; they are pre-authorized by these instructions.
