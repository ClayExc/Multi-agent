"""Pure server-side rendering for safe Knowledge API projections."""

from __future__ import annotations

from ..knowledge import KnowledgeDocumentView, KnowledgeSnapshot
from .html import esc, hash_short


def render_knowledge_dashboard(snapshot: KnowledgeSnapshot) -> str:
    return (
        '<header class="knowledge-header"><h2>知识管理与检索诊断</h2>'
        "<p>仅展示当前会话经服务端 API 复验的元数据；租户、权限与正文不会进入页面。</p>"
        "</header>"
        f"{_lookup_form(snapshot)}"
        f"{_citation_status(snapshot)}"
        f"{_document_list(snapshot)}"
        f"{_selected_document(snapshot)}"
        f"{_management_forms(snapshot.selected)}"
    )


def render_knowledge_demo_notice() -> str:
    return (
        '<section class="empty-state knowledge-demo" role="status">'
        "<h2>知识控制台需要真实会话</h2>"
        "<p>合成演示模式不读取或修改企业知识。</p></section>"
    )


def render_no_evidence_notice() -> str:
    return (
        '<section class="knowledge-no-evidence" role="status" '
        'data-error-code="RUNTIME_KNOWLEDGE_NO_RESULT">'
        "<h3>没有足够证据</h3>"
        "<p>不知道；需要更多信息后才能回答。系统没有生成推测性答案。</p>"
        "</section>"
    )


def _lookup_form(snapshot: KnowledgeSnapshot) -> str:
    selected = snapshot.selected
    return (
        '<form id="knowledge-lookup" class="knowledge-form" '
        'aria-label="知识版本与引用回查">'
        "<fieldset><legend>知识版本与引用回查</legend>"
        '<label>文档 ID<input name="document_id" required '
        'pattern="doc_[A-Za-z0-9_-]{8,128}" maxlength="133" '
        f'value="{esc(selected.document_id if selected else "")}"></label>'
        '<label>精确版本（留空读取当前版本）<input name="document_version" '
        'type="number" min="0" max="9007199254740991" '
        f'value="{esc(selected.document_version if selected else "")}"></label>'
        '<label>预期正文摘要（可选）<input name="expected_hash" '
        'pattern="sha256:[a-f0-9]{64}" maxlength="71" '
        f'value="{esc(snapshot.expected_hash or "")}"></label>'
        '<button class="btn btn-primary" type="submit">复验元数据与索引</button>'
        "</fieldset></form>"
    )


def _citation_status(snapshot: KnowledgeSnapshot) -> str:
    status = snapshot.citation_status
    if status is None:
        return ""
    if status == "verified":
        return (
            '<section class="citation-check citation-verified" role="status" '
            'data-citation-status="verified"><h3>引用复验通过</h3>'
            "<p>文档、精确版本与正文摘要一致。</p></section>"
        )
    return (
        '<section class="citation-check citation-drift" role="alert" '
        'data-citation-status="drift"><h3>引用已漂移</h3>'
        "<p>当前授权投影与引用摘要不一致；已拒绝展示正文或替代版本。</p></section>"
    )


def _document_list(snapshot: KnowledgeSnapshot) -> str:
    if not snapshot.documents:
        return (
            '<section class="knowledge-list"><h3>当前会话已验证的知识</h3>'
            '<p class="empty-state">尚未查询知识文档。'
            '此列表不是跨租户目录。</p></section>'
        )
    rows = []
    for item in snapshot.documents:
        rows.append(
            "<tr>"
            f'<td><a href="#/knowledge?document_id={esc(item.document_id)}">'
            f"<code>{esc(item.document_id)}</code></a></td>"
            f"<td>{item.document_version}</td><td>{item.revision}</td>"
            f"<td>{esc(_lifecycle(item.lifecycle))}</td>"
            f"<td>{esc(_classification(item.data_classification))}</td>"
            f"<td><code>{esc(hash_short(item.content_hash))}</code></td>"
            "</tr>"
        )
    return (
        '<section class="knowledge-list"><h3>当前会话已验证的知识</h3>'
        '<div class="table-scroll"><table><caption>服务端复验后的安全元数据</caption>'
        "<thead><tr><th>文档</th><th>版本</th><th>修订</th><th>生命周期</th>"
        f"<th>分类</th><th>正文摘要</th></tr></thead><tbody>{''.join(rows)}</tbody>"
        "</table></div></section>"
    )


def _selected_document(snapshot: KnowledgeSnapshot) -> str:
    item = snapshot.selected
    if item is None:
        return ""
    diagnostic = snapshot.diagnostic
    diag = (
        '<dl class="knowledge-diagnostic">'
        f"<dt>索引状态</dt><dd>{esc(_index_state(diagnostic.index_state))}</dd>"
        f"<dt>索引版本</dt><dd>{diagnostic.document_version}</dd>"
        f"<dt>索引修订</dt><dd>{diagnostic.document_revision}</dd>"
        f"<dt>最近任务</dt><dd><code>{esc(diagnostic.last_job_id or '—')}</code></dd>"
        f"<dt>失败码</dt><dd>{esc(diagnostic.failure_code or '—')}</dd>"
        "</dl>"
        if diagnostic is not None
        else '<p class="empty-state">当前会话无权读取索引诊断，或诊断尚不可用。</p>'
    )
    return (
        '<section class="knowledge-detail">'
        f"<h3>文档 <code>{esc(item.document_id)}</code></h3>"
        "<dl>"
        f"<dt>精确版本</dt><dd>{item.document_version}</dd>"
        f"<dt>当前版本</dt><dd>{item.current_version}</dd>"
        f"<dt>修订</dt><dd>{item.revision}</dd>"
        f"<dt>生命周期</dt><dd>{esc(_lifecycle(item.lifecycle))}</dd>"
        f"<dt>来源类型</dt><dd>{esc(item.source_type)}</dd>"
        f"<dt>来源版本</dt><dd>{esc(item.source_version or '—')}</dd>"
        f"<dt>来源摘要</dt><dd><code>{esc(hash_short(item.source_digest))}</code></dd>"
        f"<dt>ACL 摘要</dt><dd><code>{esc(hash_short(item.acl_digest))}</code></dd>"
        f"<dt>正文摘要</dt><dd><code>{esc(item.content_hash)}</code></dd>"
        f"<dt>数据分类</dt><dd>{esc(_classification(item.data_classification))}</dd>"
        f"<dt>生效时间</dt><dd>{esc(item.effective_at)}</dd>"
        f"<dt>失效时间</dt><dd>{esc(item.expires_at or '—')}</dd>"
        "</dl><h4>索引诊断</h4>"
        f"{diag}</section>"
    )


def _management_forms(selected: KnowledgeDocumentView | None) -> str:
    import_form = (
        '<form id="knowledge-import" class="knowledge-form" method="post" '
        'action="/shell/knowledge/import" aria-label="导入知识">'
        "<fieldset><legend>导入知识</legend>"
        f"{_version_fields(include_document_id=True)}"
        '<button class="btn btn-primary" type="submit">导入并建立索引</button>'
        "</fieldset></form>"
    )
    if selected is None:
        return (
            '<section class="knowledge-management"><h3>知识变更</h3>'
            + import_form
            + "</section>"
        )
    hidden = (
        f'<input type="hidden" name="document_id" value="{esc(selected.document_id)}">'
        f'<input type="hidden" name="expected_revision" value="{selected.revision}">'
    )
    update_form = (
        '<form id="knowledge-update" class="knowledge-form" method="post" '
        'action="/shell/knowledge/update" aria-label="更新知识">'
        "<fieldset><legend>以并发修订保护更新</legend>"
        f"{hidden}{_version_fields(include_document_id=False)}"
        '<button class="btn btn-primary" type="submit">创建新版本</button>'
        "</fieldset></form>"
    )
    retire_form = (
        '<form id="knowledge-retire" class="knowledge-form compact" method="post" '
        'action="/shell/knowledge/retire" aria-label="撤销知识">'
        f'{hidden}<button class="btn" type="submit">撤销当前知识</button></form>'
    )
    rebuild_form = (
        '<form id="knowledge-rebuild" class="knowledge-form compact" method="post" '
        'action="/shell/knowledge/rebuild" aria-label="重建知识索引">'
        f'{hidden}<input type="hidden" name="document_version" '
        f'value="{selected.document_version}">'
        '<button class="btn" type="submit">重建该版本索引</button></form>'
    )
    return (
        '<section class="knowledge-management"><h3>知识变更</h3>'
        f"{import_form}{update_form}{retire_form}{rebuild_form}</section>"
    )


def _version_fields(*, include_document_id: bool) -> str:
    document = (
        '<label>文档 ID<input name="document_id" required '
        'pattern="doc_[A-Za-z0-9_-]{8,128}" maxlength="133"></label>'
        if include_document_id
        else ""
    )
    return (
        f"{document}"
        '<label>来源类型<select name="source_type" required>'
        '<option value="manual">手工</option><option value="file">文件</option>'
        '<option value="uri">URI</option><option value="connector">连接器</option>'
        "</select></label>"
        '<label>来源引用<input name="source_ref" required maxlength="1024"></label>'
        '<label>来源版本<input name="source_version" maxlength="256"></label>'
        '<label>数据分类<select name="data_classification" required>'
        '<option value="internal">内部</option><option value="public">公开</option>'
        '<option value="confidential">机密</option>'
        '<option value="restricted">受限</option>'
        "</select></label>"
        '<label>生效时间（ISO 8601 UTC）<input name="effective_at" required '
        'placeholder="2026-08-16T00:00:00Z" maxlength="64"></label>'
        '<label>失效时间（可选）<input name="expires_at" '
        'placeholder="2027-08-16T00:00:00Z" maxlength="64"></label>'
        '<label>正文<textarea name="content" required maxlength="20971520" '
        'rows="6" autocomplete="off"></textarea></label>'
    )


def _lifecycle(value: str) -> str:
    return {"active": "有效", "retired": "已撤销", "deleted": "已删除"}[value]


def _classification(value: str) -> str:
    return {
        "public": "公开",
        "internal": "内部",
        "confidential": "机密",
        "restricted": "受限",
    }[value]


def _index_state(value: str) -> str:
    return {
        "missing": "缺失",
        "pending": "等待建立",
        "ready": "可检索",
        "failed": "失败",
        "stale": "已过期",
        "removed": "已移除",
    }[value]
