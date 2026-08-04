"""apps/api-local event sources for the proactive assistant (SPEC.md §13).

Distinct from personal_ai.proactive.sources, which holds sources that need
no apps/api context (gh CLI, disk, docker). TaskDeadlineSource lives here
because it reads apps/api's own Task table via tasks_repository.py.
"""
