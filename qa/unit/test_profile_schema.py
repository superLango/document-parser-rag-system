"""L1 单元测试：个人中心 Profile Schema（M7）。"""

from app.schemas.user import ProfileUpdate


def test_profile_update_accepts_all_fields():
    body = ProfileUpdate(
        email="a@b.com",
        full_name="姓名",
        phone="13800000000",
        department="研发部",
        avatar="https://example.com/a.png",
    )
    assert body.full_name == "姓名"
    assert body.department == "研发部"


def test_profile_update_allows_partial():
    body = ProfileUpdate(full_name="仅改姓名")
    assert body.email is None
    assert body.phone is None
