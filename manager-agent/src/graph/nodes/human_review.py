"""
human_review — HITL 노드 (passthrough).

실제 검토는 Streamlit UI에서 graph.update_state()로 처리됨.
interrupt_before=["human_review"] 설정으로 그래프가 여기서 일시 정지.

Demonstrates: Human-in-the-Loop 패턴
"""

from src.graph.state import ManagerState


def human_review(state: ManagerState) -> dict:
    """Passthrough — Streamlit sets review_status via graph.update_state()."""
    return {"current_stage": "human_review"}
