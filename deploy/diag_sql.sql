-- 验证 JSONB @> 查询是否匹配 bob(user_id=3)
SELECT id, name FROM knowledge_bases WHERE collaborators @> CAST('[{"user_id": 3}]' AS JSONB);
-- 对照: owner_id=3 (bob 自己的 KB)
SELECT id, name FROM knowledge_bases WHERE owner_id = 3;
-- 诊断: collaborators 字段类型
SELECT column_name, data_type FROM information_schema.columns WHERE table_name='knowledge_bases' AND column_name='collaborators';
