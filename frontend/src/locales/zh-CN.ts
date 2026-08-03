/**
 * 中文简体语言包（P3-9 i18n）。
 *
 * 当前产品定位为中文垂直领域，中文为默认语言。
 * 此文件提供基础翻译键值，未翻译的键回退到原始中文文案。
 */
export default {
  // 通用
  common: {
    save: '保存',
    cancel: '取消',
    delete: '删除',
    confirm: '确认',
    close: '关闭',
    loading: '加载中...',
    search: '搜索',
    export: '导出',
    import: '导入',
    upload: '上传',
    download: '下载',
    refresh: '刷新',
    retry: '重试',
    back: '返回',
    next: '下一步',
    previous: '上一步',
    submit: '提交',
    reset: '重置',
    all: '全部',
    none: '无',
    yes: '是',
    no: '否',
    success: '成功',
    failed: '失败',
    error: '错误',
    warning: '警告',
    info: '信息',
  },
  // 导航
  nav: {
    dashboard: '仪表盘',
    knowledgeBase: '知识库',
    settings: '系统设置',
    profile: '个人中心',
    help: '帮助文档',
    about: '关于',
    users: '用户管理',
    auditLogs: '审计日志',
  },
  // 认证
  auth: {
    login: '登录',
    logout: '退出登录',
    register: '注册',
    username: '用户名',
    password: '密码',
    loginExpired: '登录已过期，请重新登录',
  },
  // 知识库
  kb: {
    overview: '概览',
    documents: '文档',
    extraction: '抽取',
    schemas: 'Schema',
    terms: '术语',
    tasks: '任务',
    graph: '图谱',
    config: '配置',
    qa: '问答',
    members: '成员',
    search: '搜索',
  },
  // 通知
  notification: {
    title: '通知',
    markAllRead: '全部已读',
    empty: '暂无通知',
  },
} as const
