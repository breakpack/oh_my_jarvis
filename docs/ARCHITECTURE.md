# Architecture

> 이 문서는 [SPEC.md](../SPEC.md) §4(전체 아키텍처)의 요약이다. 세부 요구사항과 각 컴포넌트의 책임은 SPEC.md를 최상위 근거로 삼는다.

## 계층 개요

Personal AI OS는 네 개의 계층으로 구성된다.

```text
Clients
  → Assistant API
    → Personal AI OS Core
      → Local/Cloud Models, Second Brain (RAG/Memory), Skill Runtime
        → Data and Execution Plane
```

### 1. Clients

Web Chat, CLI, macOS Menu Bar, Mobile, Voice 등 사용자가 직접 상호작용하는 진입점. 이 저장소에서는 `apps/web`(Next.js)과 `apps/cli`(`pai`)로 구현한다.

### 2. Assistant API

`apps/api`(FastAPI)가 담당하는 계층. 인증, SSE/WebSocket 스트리밍, 파일 업로드, 이벤트 전달을 처리하며 Client와 Core 사이의 유일한 진입점이다.

### 3. Personal AI OS Core

`personal_ai/` 패키지가 소유하는 핵심 도메인 로직. Request Analyzer, Context Builder, Intent Router, Skill Resolver, Model Router, Workflow Engine, Planner, Policy Engine, Approval Manager, Tool Executor, Result Verifier, Memory Writer, Audit Logger로 구성된다. 권한·승인·검증·감사는 항상 이 계층이 소유하며, 외부 프레임워크나 Skill에 위임하지 않는다(SPEC.md §3.5).

Core는 아래 네 방향으로 위임한다.

- **Local/Cloud Models** — Ollama/MLX 기반 로컬 모델을 우선 사용하고, 정책에 따라서만 Cloud 모델로 승격한다(SPEC.md §3.1, §11).
- **Second Brain** — RAG/Memory 계층. 문서와 대화 요약, 프로젝트 기억을 pgvector 기반으로 검색한다(SPEC.md §8).
- **Skill Runtime** — MCP 및 Native Skill 실행 환경. Tool은 Policy Engine을 거쳐 정규화된 뒤에만 모델에 노출된다(SPEC.md §6, §7).

### 4. Data and Execution Plane

PostgreSQL/pgvector, Redis, Object Storage와 GitHub/Notion/Gmail/Calendar/Browser/Files/Shell Sandbox/Docker/Kubernetes 등 실제 상태를 저장하고 실행하는 계층. 모든 외부 상태 변경은 Core의 Policy Engine과 Approval Manager를 거친다.

## 현재 구현 상태

이 문서 작성 시점 기준으로 Phase 0/1(Repository Bootstrap, Local Chat Vertical Slice)이 진행 중이다. 각 계층의 실제 구현 범위와 완료 조건은 [ROADMAP.md](ROADMAP.md)를 참고한다. 계층별 세부 인터페이스(Tool, Skill, Model Provider 등)는 SPEC.md §5~§11에 정의되어 있으며, 이 문서는 그 요약일 뿐 대체하지 않는다.
