"""L1 单元测试：RBAC 权限目录与矩阵不变量。"""

import pytest
from pydantic import ValidationError

from app.models.rbac import (
    PERMISSION_CATALOG,
    PERMISSION_CODES,
    ROLE_PERMISSION_MATRIX,
    ROLE_SUPER_ADMIN,
    SYSTEM_ROLES,
    SYSTEM_ROLE_INFO,
)
from app.schemas.rbac import RoleCreate, RolePermissionsUpdate


def test_catalog_codes_unique():
    codes = [c for c, _, _, _ in PERMISSION_CATALOG]
    assert len(codes) == len(set(codes)) == len(PERMISSION_CODES)
    assert len(codes) == 11


def test_matrix_covers_only_catalog_codes():
    for role_code, perm_codes in ROLE_PERMISSION_MATRIX.items():
        assert role_code in SYSTEM_ROLES
        assert set(perm_codes) <= PERMISSION_CODES


def test_super_admin_owns_all_permissions():
    assert set(ROLE_PERMISSION_MATRIX[ROLE_SUPER_ADMIN]) == PERMISSION_CODES


def test_system_role_info_covers_matrix():
    assert set(SYSTEM_ROLE_INFO) == SYSTEM_ROLES
    assert set(ROLE_PERMISSION_MATRIX) == SYSTEM_ROLES


def test_role_create_code_validation():
    RoleCreate(code="data_operator", name="数据运营")
    with pytest.raises(ValidationError):
        RoleCreate(code="Data_Operator", name="x")
    with pytest.raises(ValidationError):
        RoleCreate(code="ab", name="x")
    with pytest.raises(ValidationError):
        RoleCreate(code="has space", name="x")


def test_role_permissions_update_dedupe():
    body = RolePermissionsUpdate(permission_codes=["user.view", "user.view", "user.delete"])
    assert body.permission_codes == ["user.view", "user.delete"]
