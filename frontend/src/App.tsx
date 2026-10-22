import { useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Avatar, Button, Dropdown, Grid, Layout, Menu, Spin, Typography } from "antd";
import {
  BarChartOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  InboxOutlined,
  LineChartOutlined,
  LogoutOutlined,
  ScanOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Stock from "./pages/Stock";
import Receiving from "./pages/Receiving";
import Expiry from "./pages/Expiry";
import Sales from "./pages/Sales";
import OnlineOrders from "./pages/OnlineOrders";
import Forecast from "./pages/Forecast";
import Purchasing from "./pages/Purchasing";
import OrderCard from "./pages/OrderCard";
import Reports from "./pages/Reports";
import Nsi from "./pages/Nsi";
import Admin from "./pages/Admin";
import Profile from "./pages/Profile";

const { Sider, Header, Content } = Layout;

interface Item {
  key: string;
  label: string;
  icon: JSX.Element;
  roles: string[];
}

// Пункты меню по ролям (ПР 3, табл. 3.3; ПР 7-8, варианты использования)
const ITEMS: Item[] = [
  { key: "/", label: "Главная", icon: <DashboardOutlined />, roles: [] },
  { key: "/stock", label: "Запасы и партии", icon: <InboxOutlined />, roles: ["storekeeper", "florist", "buyer", "director", "analyst", "shop_manager"] },
  { key: "/receiving", label: "Приёмка (ТСД)", icon: <ScanOutlined />, roles: ["storekeeper"] },
  { key: "/expiry", label: "Сроки и уценка", icon: <ClockCircleOutlined />, roles: ["florist", "storekeeper", "director", "buyer"] },
  { key: "/sales", label: "Продажи", icon: <ShoppingOutlined />, roles: ["florist", "director", "analyst", "buyer", "shop_manager", "storekeeper"] },
  { key: "/online", label: "Интернет-заказы", icon: <GlobalOutlined />, roles: ["shop_manager", "director", "florist"] },
  { key: "/forecast", label: "Прогноз спроса", icon: <LineChartOutlined />, roles: ["buyer", "analyst", "director", "florist", "shop_manager"] },
  { key: "/purchasing", label: "Закупки", icon: <ShoppingCartOutlined />, roles: ["buyer", "director", "storekeeper", "analyst"] },
  { key: "/reports", label: "Отчёты", icon: <BarChartOutlined />, roles: ["director", "analyst", "buyer"] },
  { key: "/nsi", label: "Справочники", icon: <DatabaseOutlined />, roles: [] },
  { key: "/admin", label: "Администрирование", icon: <SettingOutlined />, roles: ["director", "analyst"] },
];

export default function App() {
  const { user, ready, logout, can } = useAuth();
  const loc = useLocation();
  const screens = Grid.useBreakpoint();
  const [collapsed, setCollapsed] = useState(false);

  if (!ready) return <Spin fullscreen />;
  if (!user) return <Login />;

  const items = ITEMS.filter((i) => can(...i.roles));
  const selected = items
    .map((i) => i.key)
    .filter((k) => (k === "/" ? loc.pathname === "/" : loc.pathname.startsWith(k)))
    .slice(-1);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        breakpoint="lg"
        collapsedWidth={screens.xs ? 0 : 64}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={232}
        style={{ background: "#1f4d33" }}
      >
        <div className="logo">
          <img src="/favicon.svg" alt="" />
          {!collapsed && <span>ФлораПлан</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selected}
          style={{ background: "#1f4d33" }}
          items={items.map((i) => ({ key: i.key, icon: i.icon, label: <Link to={i.key}>{i.label}</Link> }))}
          onClick={() => screens.xs && setCollapsed(true)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: "#fff", padding: "0 16px", display: "flex", alignItems: "center", gap: 12 }}>
          <Typography.Text type="secondary" style={{ flex: 1, overflow: "hidden", whiteSpace: "nowrap" }}>
            Планирование закупок и продаж цветочной продукции
          </Typography.Text>
          <Dropdown
            menu={{
              items: [
                { key: "p", icon: <UserOutlined />, label: <Link to="/profile">Профиль и пароль</Link> },
                { key: "o", icon: <LogoutOutlined />, label: "Выйти", onClick: logout },
              ],
            }}
          >
            <Button type="text" icon={<Avatar size="small" icon={<UserOutlined />} />}>
              {!screens.xs && (
                <span>
                  {user.full_name} · <Typography.Text type="secondary">{user.role_name}</Typography.Text>
                </span>
              )}
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/stock" element={<Stock />} />
            <Route path="/receiving" element={<Receiving />} />
            <Route path="/expiry" element={<Expiry />} />
            <Route path="/sales" element={<Sales />} />
            <Route path="/online" element={<OnlineOrders />} />
            <Route path="/forecast" element={<Forecast />} />
            <Route path="/purchasing" element={<Purchasing />} />
            <Route path="/purchasing/orders/:id" element={<OrderCard />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/nsi" element={<Nsi />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}
