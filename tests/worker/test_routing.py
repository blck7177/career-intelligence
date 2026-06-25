"""
Unit tests for task routing logic.
No IO — pure domain logic.
"""

from __future__ import annotations

import pytest

from packages.domain.agent_jobs.routing import (
    ExecutionMode,
    celery_queue_for_task_type,
    get_agent_id,
    get_skill_version,
    route_task,
)


class TestRouteTask:
    def test_job_discovery_routes_openclaw(self):
        assert route_task("agent.job_discovery") == ExecutionMode.OPENCLAW

    def test_job_research_routes_openclaw(self):
        assert route_task("agent.job_research") == ExecutionMode.OPENCLAW

    def test_run_reflection_routes_openclaw(self):
        assert route_task("agent.run_reflection") == ExecutionMode.OPENCLAW

    def test_job_report_routes_deterministic(self):
        assert route_task("job_report") == ExecutionMode.DETERMINISTIC

    def test_fit_report_routes_deterministic(self):
        assert route_task("fit_report") == ExecutionMode.DETERMINISTIC

    def test_profile_import_routes_deterministic(self):
        assert route_task("profile_import") == ExecutionMode.DETERMINISTIC

    def test_unknown_type_routes_deterministic(self):
        assert route_task("unknown_task") == ExecutionMode.DETERMINISTIC


class TestGetAgentId:
    def test_discovery_maps_to_search_agent(self):
        assert get_agent_id("agent.job_discovery") == "career-search-agent"

    def test_research_maps_to_research_agent(self):
        assert get_agent_id("agent.job_research") == "career-research-agent"

    def test_reflection_maps_to_reflect_agent(self):
        assert get_agent_id("agent.run_reflection") == "career-reflect-agent"

    def test_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="No agent mapped"):
            get_agent_id("unknown_task")


class TestGetSkillVersion:
    def test_search_agent_has_skill_version(self):
        v = get_skill_version("career-search-agent")
        assert v.startswith("career-search-")

    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="No skill version"):
            get_skill_version("unknown-agent")


class TestCeleryQueueForTaskType:
    """
    Verifies that agent tasks route to the "agent" queue and deterministic tasks
    route to the "fast" queue.  This aligns with the two-worker-service architecture:
      worker-fast  (--queues=fast,  concurrency=2)
      worker-agent (--queues=agent, concurrency=1)
    """

    def test_discovery_routes_to_agent_queue(self):
        assert celery_queue_for_task_type("agent.job_discovery") == "agent"

    def test_research_routes_to_agent_queue(self):
        assert celery_queue_for_task_type("agent.job_research") == "agent"

    def test_reflection_routes_to_agent_queue(self):
        assert celery_queue_for_task_type("agent.run_reflection") == "agent"

    def test_job_report_routes_to_fast_queue(self):
        assert celery_queue_for_task_type("job_report") == "fast"

    def test_fit_report_routes_to_fast_queue(self):
        assert celery_queue_for_task_type("fit_report") == "fast"

    def test_profile_import_routes_to_fast_queue(self):
        assert celery_queue_for_task_type("profile_import") == "fast"

    def test_unknown_type_routes_to_fast_queue(self):
        assert celery_queue_for_task_type("unknown_task") == "fast"

    def test_all_openclaw_types_route_to_agent(self):
        """Guarantee alignment between ExecutionMode.OPENCLAW and queue='agent'."""
        from packages.domain.agent_jobs.routing import _OPENCLAW_TASK_TYPES
        for task_type in _OPENCLAW_TASK_TYPES:
            assert celery_queue_for_task_type(task_type) == "agent", (
                f"task_type={task_type!r} is OPENCLAW but does not route to 'agent' queue"
            )
