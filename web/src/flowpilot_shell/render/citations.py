"""Result artifact and citation fragment."""

from __future__ import annotations

from ..models import ResultArtifactView
from .html import esc, hash_short


def render_result_artifact(artifact: ResultArtifactView) -> str:
    citations = "".join(
        f'<li class="citation-item">'
        f'<span class="citation-source">{esc(citation.source_ref)}</span>'
        f'<span class="citation-section">{esc(citation.section)}</span>'
        f'<span class="citation-version">{esc(citation.document_version)}</span>'
        f'<span class="citation-hash">{hash_short(citation.content_hash)}</span>'
        f"</li>"
        for citation in artifact.citations
    )
    return (
        f"<h3>执行结果</h3>"
        f'<div class="result-content">{esc(artifact.content)}</div>'
        f'<p class="result-ref">结果引用：<code>{esc(artifact.result_ref)}</code>'
        f"（{esc(artifact.media_type)}）</p>"
        f"<h4>引用来源</h4>"
        f'<ul class="citation-list">{citations}</ul>'
    )
