import { computed } from 'vue'
import { useKbStore } from '@/stores/kb'
import type { KbRole } from '@/api/types'

/**
 * 知识库权限工具
 *
 * 角色权限矩阵：
 *   viewer  : 只读（查看文档/抽取结果/配置/问答）
 *   editor  : viewer + 上传文档/执行抽取/管理术语
 *   admin   : editor + 管理配置/成员/Hook/模板
 *   owner   : admin + 删除知识库/转让所有权
 */
const ROLE_LEVEL: Record<KbRole, number> = {
  viewer: 1,
  editor: 2,
  admin: 3,
  owner: 4,
}

export function useKbPermission() {
  const kbStore = useKbStore()
  const role = computed<KbRole | null>(() => kbStore.currentKb?.my_role ?? null)
  const roleLevel = computed(() => (role.value ? ROLE_LEVEL[role.value] : 0))

  const isViewer = computed(() => roleLevel.value >= 1)
  const isEditor = computed(() => roleLevel.value >= 2)
  const isAdmin = computed(() => roleLevel.value >= 3)
  const isOwner = computed(() => roleLevel.value >= 4)

  /** 判断当前角色是否达到指定角色级别 */
  function can(requiredRole: KbRole): boolean {
    return roleLevel.value >= ROLE_LEVEL[requiredRole]
  }

  return {
    role,
    roleLevel,
    isViewer,
    isEditor,
    isAdmin,
    isOwner,
    can,
  }
}
