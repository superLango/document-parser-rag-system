"""L1 单元测试：权限点依赖行为（M8）。"""


async def test_member_without_permission_rejected(client, member_user):
    token, _, _ = member_user
    resp = await client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 20003


async def test_super_admin_passes_permission_dep(client, super_token):
    resp = await client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {super_token}"}
    )
    assert resp.status_code == 200
