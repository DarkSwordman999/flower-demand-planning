import { Link } from "react-router-dom";
import { Alert, Card, Col, Row, Spin, Statistic, Typography } from "antd";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import dayjs from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { useLoad, useSettings } from "../hooks";
import { d, money, num } from "../format";

export default function Dashboard() {
  const { user, can } = useAuth();
  const { data, loading } = useLoad(() => api.get("/api/dashboard"));
  const st = useSettings();
  if (loading && !data) return <Spin />;
  if (!data) return null;

  const kpi = (title: string, value: any, to?: string, suffix?: string, warn?: boolean) => (
    <Col xs={24} sm={12} lg={6}>
      <Card size="small" className="kpi">
        <Statistic
          title={to ? <Link to={to}>{title}</Link> : title}
          value={value ?? "—"}
          suffix={suffix}
          valueStyle={warn ? { color: "#cf1322" } : undefined}
        />
      </Card>
    </Col>
  );

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Здравствуйте, {user?.full_name.split(" ")[1] || user?.full_name}
      </Typography.Title>
      {data.forecast_stale && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            data.forecast_date
              ? `Прогноз на сегодня не рассчитан — используется прогноз от ${d(data.forecast_date)}`
              : "Прогноз спроса ещё не рассчитан"
          }
          action={can("analyst", "buyer") ? <Link to="/forecast">Рассчитать</Link> : undefined}
        />
      )}
      <Row gutter={[16, 16]}>
        {kpi("Продажи сегодня, руб.", money(data.sales_today), "/sales")}
        {kpi("Продажи за 7 дней, руб.", money(data.sales_week), "/reports")}
        {kpi("Списания за 30 дней", num(data.writeoff_share_pct), "/reports", "% закупок", (data.writeoff_share_pct ?? 0) > 10)}
        {kpi("WAPE прогноза (4 недели)", num(data.forecast_wape_pct), "/reports", "%", (data.forecast_wape_pct ?? 0) > 25)}
        {kpi(`Партии со сроком ≤ ${st.expiring_days} дн.`, data.expiring_batches, "/expiry")}
        {kpi("Рекомендуется уценить", data.markdown_needed, "/expiry", undefined, data.markdown_needed > 0)}
        {kpi("Просрочено (к списанию)", data.expired_batches, "/expiry", undefined, data.expired_batches > 0)}
        {kpi("Дней дефицита за неделю", data.stockouts_week, "/stock")}
        {kpi("Заказы на согласовании", data.orders_awaiting_approval, "/purchasing", undefined, data.orders_awaiting_approval > 0)}
        {kpi("Заказы в пути", data.orders_in_transit, can("storekeeper") ? "/receiving" : "/purchasing")}
        {kpi("Черновики заказов", data.orders_drafts, "/purchasing")}
        {kpi("Онлайн-заказы в работе", data.online_to_process, "/online")}
      </Row>
      <Card title="Выручка за 30 дней, руб." size="small" style={{ marginTop: 16 }}>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data.sales_daily}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" />
            <XAxis dataKey="day" tickFormatter={(v) => dayjs(v).format("DD.MM")} minTickGap={20} />
            <YAxis tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)} тыс.` : v)} width={70} />
            <Tooltip formatter={(v: number) => money(v)} labelFormatter={(v) => d(v)} />
            <Area type="monotone" dataKey="revenue" name="Выручка" stroke="#2f7a4f" fill="#cfe6d6" />
          </AreaChart>
        </ResponsiveContainer>
      </Card>
    </>
  );
}
