-- 数据初始化清理：保留系统表 + 航天航空 KB（抽取配置/术语集），清空文档与向量，删除其他 KB
-- 以超级用户执行（绕过 RLS）

-- 1) 清空任务与队列（避免 arq 重复消费历史任务）
TRUNCATE task_outbox, task_dead_letter, integration_tasks, document_tasks;

-- 2) 清空文档与向量数据（重新上传解析后重建）
TRUNCATE extraction_history, extraction_results, kb_bm25_stats, text_chunks, document_chunks, documents CASCADE;

-- 3) 删除其他知识库（FK 级联清理其抽取配置/术语集/成员等）
DELETE FROM knowledge_bases WHERE id <> '25e7d8ef-6268-42d7-ba0c-62516ffc93f9';

-- 4) 邀请数据无航天航空记录，清空
DELETE FROM kb_invitations;

-- 校验（应输出 1）
SELECT count(*) AS remaining_kbs FROM knowledge_bases;
