# Contract conformance

`validate.py` 是 M0 公共边界的底层门禁，覆盖：

- 20 个 Draft 2020-12 Schema 的编译与 `$ref` 注册。
- `contract-set.v1.json` 的原始文件 SHA-256、稳定内容摘要、Review Attestation 与生命周期规则。
- `rc2-cases.json` 的 Schema 正负例、变异用例和跨对象语义负例。
- TaskCommand 摘要重算以及命令与 SecurityContext 的租户、主体和创建用途绑定。
- Tool、Approval、Policy、Context、Runtime、Audit/Security 之间的身份、摘要、回读和链完整性约束。
- Evaluation Registry、Dataset、Fixture 与 Feature Traceability 的结构、全局 ID 唯一性、配额及跨文件引用。
- 未注册 Feature、Category、Assertion、Rubric 和漂移的 Registry/Dataset/Fixture Hash 必须在语义门禁失败。

运行：

```bash
python contracts/conformance/validate.py
```

当前根级 `make test-contract` 尚未实现；在 S2-RUNTIME 把 `jsonschema>=4.23` 纳入公共开发依赖、S4-QUALITY 接入验收入口前，本命令仅是 WP-000 底层验证，不等同于完整实现验收。
