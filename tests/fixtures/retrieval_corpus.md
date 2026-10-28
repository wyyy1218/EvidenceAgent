# EvidenceAgent 检索夹具

本文档用于 S12—S13 固定功能夹具。预期位置在运行前登记。

## 实体与版本

产品代号 **NebulaGate** 发布版本 **v2.4.1**。
兼容 API 名称：`CreateEvidenceSession` 与 `ListSourceVersions`。

## 中文问句段落

离线部署说明：方案甲可在断网环境中独立运行，无需外网搜索。

## English API notes

The `CreateEvidenceSession` endpoint accepts a project_id and returns a session token.
Rate limit is 60 requests per minute for NebulaGate v2.4.1.

## 多文档线索

当比较多份资料时，以 source_version_id 锁定原文，不得覆盖旧证据。
