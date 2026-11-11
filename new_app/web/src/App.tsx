import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { to: "/", label: "文档库", end: true },
  { to: "/runs", label: "运行记录" },
  { to: "/dictionary", label: "业务词典" },
  { to: "/recipes", label: "配方版本" }
];

export default function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>Hanson</strong>
          <span>标准拆分平台</span>
        </div>
        <nav>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">M0 骨架 · 无登录/租户</div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
