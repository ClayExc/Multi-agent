from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .errors import GraphError, GraphErrorCode

FLOWPILOT_GRAPH_ID = "flowpilot_it_service"
FLOWPILOT_GRAPH_FACTORY_ID = "flowpilot.graph.factory.v1"

GraphStateValue = Mapping[str, Any]
GraphUpdate = Mapping[str, Any]
NodeCallback = Callable[[GraphStateValue], Awaitable[GraphUpdate]]
RouteCallback = Callable[[GraphStateValue], str | Sequence[str]]


@dataclass(frozen=True, slots=True)
class FlowPilotGraphNodes:
    prepare: NodeCallback
    build_context: NodeCallback
    route_request: NodeCallback
    route_after_request: RouteCallback
    clarification_interrupt: NodeCallback
    knowledge_read: NodeCallback
    service_read: NodeCallback
    join_reads: NodeCallback
    handoff: NodeCallback
    approval_interrupt: NodeCallback
    run_agent: NodeCallback
    route_result: NodeCallback
    route_after_result: RouteCallback
    retry: NodeCallback
    compensate: NodeCallback
    finalize: NodeCallback
    # M5-1 (FP-FLOW-003): optional third parallel read branch.  The base
    # topology keeps the two-branch fan-out (knowledge_read + service_read)
    # so existing graphs and the studio snapshot are untouched; graphs that
    # provide this node compile the three-branch variant and receive a
    # variant-aware topology digest.
    permission_read: NodeCallback | None = None


@dataclass(frozen=True, slots=True)
class GraphDefinition:
    graph_id: str
    factory_id: str
    topology_digest: str
    graph: CompiledStateGraph[Any, Any, Any, Any]


_STABLE_NODES = (
    "prepare",
    "build_context",
    "route_request",
    "clarification_interrupt",
    "knowledge_read",
    "service_read",
    "join_reads",
    "handoff",
    "approval_interrupt",
    "run_agent",
    "route_result",
    "retry",
    "compensate",
    "finalize",
)

_STABLE_EDGES: tuple[dict[str, Any], ...] = (
    {"source": "__start__", "target": "prepare"},
    {"source": "prepare", "target": "build_context"},
    {"source": "build_context", "target": "route_request"},
    {
        "source": "route_request",
        "condition": "clarification",
        "target": "clarification_interrupt",
    },
    {
        "source": "route_request",
        "condition": "parallel_reads",
        "target": ["knowledge_read", "service_read"],
    },
    {
        "source": "route_request",
        "condition": "approval",
        "target": "approval_interrupt",
    },
    {
        "source": "route_request",
        "condition": "run_agent",
        "target": "run_agent",
    },
    {
        "source": "route_request",
        "condition": "terminate",
        "target": "finalize",
    },
    {"source": "clarification_interrupt", "target": "build_context"},
    {
        "source": ["knowledge_read", "service_read"],
        "target": "join_reads",
    },
    {"source": "join_reads", "target": "handoff"},
    {"source": "handoff", "target": "route_request"},
    {"source": "approval_interrupt", "target": "run_agent"},
    {"source": "run_agent", "target": "route_result"},
    {
        "source": "route_result",
        "condition": "retry",
        "target": "retry",
    },
    {
        "source": "route_result",
        "condition": "compensate",
        "target": "compensate",
    },
    {
        "source": "route_result",
        "condition": "finalize",
        "target": "finalize",
    },
    {"source": "retry", "target": "run_agent"},
    {"source": "compensate", "target": "finalize"},
    {"source": "finalize", "target": "__end__"},
)


def topology_snapshot(
    extra_parallel_branches: Sequence[str] = (),
) -> dict[str, Any]:
    """Snapshot of the stable FlowPilot topology.

    ``extra_parallel_branches`` is M5-1 (FP-FLOW-003): graphs that register
    an additional parallel read node (e.g. ``permission_read``) pass it here
    so their topology digest covers the three-branch fan-out.  The default
    (no extra branch) reproduces the historic snapshot byte for byte, so the
    studio snapshot test and worker/studio parity are unaffected.
    """
    content: dict[str, Any] = {
        "schema": "flowpilot.graph-topology.v1",
        "graph_id": FLOWPILOT_GRAPH_ID,
        "factory_id": FLOWPILOT_GRAPH_FACTORY_ID,
        "nodes": list(_STABLE_NODES) + list(extra_parallel_branches),
        "edges": _topology_edges(extra_parallel_branches),
    }
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    content["topology_digest"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return content


def _topology_edges(extra_parallel_branches: Sequence[str]) -> list[dict[str, Any]]:
    parallel_targets = ["knowledge_read", "service_read", *extra_parallel_branches]
    edges = [dict(edge) for edge in _STABLE_EDGES]
    for edge in edges:
        if (
            edge.get("condition") == "parallel_reads"
            and edge.get("target") == ["knowledge_read", "service_read"]
        ):
            edge["target"] = list(parallel_targets)
        elif edge.get("source") == ["knowledge_read", "service_read"]:
            edge["source"] = list(parallel_targets)
    return edges


def build_flowpilot_it_service_graph(
    state_schema: type[Any],
    nodes: FlowPilotGraphNodes,
    *,
    checkpointer: Any = None,
) -> GraphDefinition:
    """Compile the one stable FlowPilot topology for Worker and Studio."""

    builder = StateGraph(state_schema)
    add_node = cast(Any, builder.add_node)
    add_node("prepare", nodes.prepare)
    add_node("build_context", nodes.build_context)
    add_node("route_request", nodes.route_request)
    add_node(
        "clarification_interrupt",
        nodes.clarification_interrupt,
    )
    add_node("knowledge_read", nodes.knowledge_read)
    add_node("service_read", nodes.service_read)
    # M5-1 (FP-FLOW-003): the optional third parallel read branch joins the
    # fan-out and the join barrier; without it the compiled topology is
    # byte-identical to the historic two-branch graph.
    extra_parallel_branches: list[str] = []
    if nodes.permission_read is not None:
        add_node("permission_read", nodes.permission_read)
        extra_parallel_branches.append("permission_read")
    add_node("join_reads", nodes.join_reads)
    add_node("handoff", nodes.handoff)
    add_node("approval_interrupt", nodes.approval_interrupt)
    add_node("run_agent", nodes.run_agent)
    add_node("route_result", nodes.route_result)
    add_node("retry", nodes.retry)
    add_node("compensate", nodes.compensate)
    add_node("finalize", nodes.finalize)

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "build_context")
    builder.add_edge("build_context", "route_request")
    parallel_targets = ["knowledge_read", "service_read", *extra_parallel_branches]
    builder.add_conditional_edges(
        "route_request",
        nodes.route_after_request,
        {
            "clarification": "clarification_interrupt",
            "knowledge_read": "knowledge_read",
            "service_read": "service_read",
            **{
                branch: branch
                for branch in extra_parallel_branches
            },
            "approval": "approval_interrupt",
            "run_agent": "run_agent",
            "terminate": "finalize",
        },
    )
    builder.add_edge("clarification_interrupt", "build_context")
    builder.add_edge(
        parallel_targets,
        "join_reads",
    )
    builder.add_edge("join_reads", "handoff")
    builder.add_edge("handoff", "route_request")
    builder.add_edge("approval_interrupt", "run_agent")
    builder.add_edge("run_agent", "route_result")
    builder.add_conditional_edges(
        "route_result",
        nodes.route_after_result,
        {
            "retry": "retry",
            "compensate": "compensate",
            "finalize": "finalize",
        },
    )
    builder.add_edge("retry", "run_agent")
    builder.add_edge("compensate", "finalize")
    builder.add_edge("finalize", END)

    snapshot = topology_snapshot(extra_parallel_branches)
    compiled = builder.compile(checkpointer=checkpointer)
    return GraphDefinition(
        graph_id=FLOWPILOT_GRAPH_ID,
        factory_id=FLOWPILOT_GRAPH_FACTORY_ID,
        topology_digest=str(snapshot["topology_digest"]),
        graph=compiled,
    )


def assert_same_graph_factory(
    worker_definition: GraphDefinition,
    studio_definition: GraphDefinition,
) -> None:
    if (
        worker_definition.graph_id != FLOWPILOT_GRAPH_ID
        or studio_definition.graph_id != FLOWPILOT_GRAPH_ID
        or worker_definition.factory_id != FLOWPILOT_GRAPH_FACTORY_ID
        or studio_definition.factory_id != FLOWPILOT_GRAPH_FACTORY_ID
        or worker_definition.topology_digest
        != studio_definition.topology_digest
    ):
        raise GraphError(
            GraphErrorCode.GRAPH_FACTORY_DIVERGED,
            "Worker and Studio must use the same graph factory and topology",
        )
