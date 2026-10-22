import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Card, Col, DatePicker, Empty, Popover, Progress, Row, Select, Space, Statistic, Table, Tabs, Tag, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { d, iso, money, num, ORDER_COLORS } from "../format";

export default function Purchasing() {
  const { can } = useAuth();
  const budget = useLoad<any>(() => api.get("/api/purchasing/budget"));
  const b = budget.data;
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Планирование закупок
      </Typography.Title>
      {b && (
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} md={12}>
            <Card size="small">
              <Statistic title={`Бюджет закупок на неделю ${d(b.week_from)}–${d(b.week_to)}, руб.`} value={money(b.budget)} />
              <Progress percent={Math.round((b.committed / b.budget) * 100)} status={b.committed > b.budget ? "exception" : "normal"} format={() => `использовано ${money(b.committed)}`} />
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card size="small">
              <Statistic title="Заказы на согласовании у директора" value={b.awaiting_approval} valueStyle={b.awaiting_approval ? { color: "#d46b08" } : undefined} />
            </Card>
          </Col>
        </Row>
      )}
      <Tabs
        defaultActiveKey={can("buyer") ? "plan" : "orders"}
        items={[
          ...(can("buyer", "director") ? [{ key: "plan", label: "Расчёт заказа", children: <Plan onCreated={budget.reload} /> }] : []),
          { key: "orders", label: "Заказы поставщикам", children: <Orders /> },
          { key: "sched", label: "График к празднику", children: <Schedule /> },
        ]}
      />
    </>
  );
}

export function CalcPopover({ calc }: { calc: any }) {
  if (!calc || calc.D === undefined) return null;
  return (
    <Popover
      title="Обоснование расчёта"
      content={
        <div style={{ maxWidth: 360 }}>
          <div>Уровень обслуживания α = {num(calc.alpha, 3)} (Cu / (Cu + Co))</div>
          <div>
            Спрос до следующей поставки: средний {num(calc.mean_demand)}, квантиль α — D = {num(calc.D)} ({calc.days} дн.)
          </div>
          <div>Запас, который успеет продаться: S = {num(calc.S)}</div>
          <div>Заказы в пути: Z = {num(calc.Z)}</div>
          <div>Q = max(0, D − S − Z) = {num(calc.q_raw)}</div>
          <div>Предел — продажи за срок годности: {num(calc.cap_shelf_life)}</div>
          {calc.scenario_days?.length > 0 && <div>Сценарий праздника: {calc.scenario_days.map(d).join(", ")}</div>}
          {calc.notes?.map((n: string) => (
            <div key={n}>• {n}</div>
          ))}
        </div>
      }
    >
      <a>расчёт</a>
    </Popover>
  );
}

function Plan({ onCreated }: { onCreated: () => void }) {
  const { can } = useAuth();
  const nav = useNavigate();
  const suppliers = useRefs("suppliers");
  const scenarios = useLoad<any[]>(() => api.get("/api/nsi/scenarios"));
  const [sup, setSup] = useState<number>();
  const [delivery, setDelivery] = useState<Dayjs | null>(null);
  const [scen, setScen] = useState<number>();
  const [plan, setPlan] = useState<any>(null);
  const { busy, run } = useAction();
  const body = () => ({ supplier_id: sup, delivery_date: iso(delivery), scenario_id: scen });

  const calc = async () => {
    const p = await run(() => api.post("/api/purchasing/plan", body()));
    if (p) setPlan(p);
  };
  const create = async () => {
    const o = await run(() => api.post("/api/purchasing/orders", body()), "Черновик заказа создан");
    if (o) {
      onCreated();
      nav(`/purchasing/orders/${o.id}`);
    }
  };
  const selected = suppliers.find((s) => s.id === sup);

  return (
    <>
      <div className="toolbar">
        <Select
          placeholder="Поставщик"
          style={{ minWidth: 300 }}
          value={sup}
          onChange={(v) => {
            setSup(v);
            setPlan(null);
          }}
          options={suppliers.filter((s) => s.active).map((s) => ({ value: s.id, label: `${s.name} (${s.lead_time_days} дн.)` }))}
        />
        <DatePicker
          placeholder="Дата поставки (по сроку)"
          format="DD.MM.YYYY"
          value={delivery}
          onChange={setDelivery}
          disabledDate={(x) => !!selected && x < dayjs().add(selected.lead_time_days, "day").startOf("day")}
        />
        <Select
          placeholder="Сценарий праздника (авто)"
          allowClear
          style={{ minWidth: 240 }}
          value={scen}
          onChange={setScen}
          options={(scenarios.data || []).filter((s) => s.approved).map((s) => ({ value: s.id, label: `${s.name} (${d(s.event_date)})` }))}
        />
        <Button type="primary" disabled={!sup} loading={busy} onClick={calc}>
          Рассчитать
        </Button>
      </div>
      {!plan && <Empty description="Выберите поставщика и рассчитайте рекомендуемый заказ" />}
      {plan && (
        <>
          <Card size="small" style={{ marginBottom: 12 }}>
            <Space wrap size="large">
              <span>
                Поставка <b>{d(plan.delivery_date)}</b>, следующая — {d(plan.next_delivery_date)}
              </span>
              <span>Прогноз от {d(plan.forecast_base)}</span>
              {plan.scenario && <Tag color="magenta">сценарий: {plan.scenario}</Tag>}
              <span>
                Сумма заказа: <b>{money(plan.total)}</b> руб. (минимум поставщика {money(plan.min_order_sum)})
              </span>
              {plan.over_budget && <Tag color="orange">потребуется утверждение директора</Tag>}
            </Space>
          </Card>
          {plan.warnings.map((w: string) => (
            <Alert key={w} type="warning" showIcon message={w} style={{ marginBottom: 8 }} />
          ))}
          <Table<any>
            rowKey="product_id"
            size="small"
            dataSource={plan.lines}
            pagination={false}
            scroll={{ x: 1000 }}
            columns={[
              { title: "Товар", dataIndex: "product" },
              { title: "ABC", dataIndex: "abc", width: 55, render: (v) => <Tag color={{ A: "green", B: "blue", C: "default" }[v as string]}>{v}</Tag> },
              { title: "Спрос до след. поставки", width: 120, align: "right", render: (_, r) => num(r.calc.mean_demand) },
              { title: "D (квантиль α)", width: 110, align: "right", render: (_, r) => num(r.calc.D) },
              { title: "S", width: 70, align: "right", render: (_, r) => num(r.calc.S) },
              { title: "Z", width: 70, align: "right", render: (_, r) => num(r.calc.Z) },
              { title: "Кратность", dataIndex: "pack_multiple", width: 90, align: "right" },
              { title: "Рекомендация", dataIndex: "ordered_qty", width: 110, align: "right", render: (v) => <b>{num(v)}</b> },
              { title: "Цена", dataIndex: "price", width: 90, align: "right", render: money },
              { title: "Сумма", width: 110, align: "right", render: (_, r) => money(r.ordered_qty * r.price) },
              { title: "", width: 80, render: (_, r) => <CalcPopover calc={r.calc} /> },
            ]}
          />
          {can("buyer") && (
            <Button type="primary" style={{ marginTop: 12 }} loading={busy} onClick={create} disabled={plan.total <= 0}>
              Создать черновик заказа
            </Button>
          )}
        </>
      )}
    </>
  );
}

function Orders() {
  const nav = useNavigate();
  const [status, setStatus] = useState<string | undefined>();
  const { data, loading } = useLoad<any[]>(() => api.get("/api/purchasing/orders", { status }), [status]);
  return (
    <>
      <div className="toolbar">
        <Select
          placeholder="Все статусы"
          allowClear
          style={{ width: 240 }}
          value={status}
          onChange={setStatus}
          options={[
            { value: "draft", label: "Черновики" },
            { value: "approval", label: "На согласовании" },
            { value: "approved,sent,confirmed,in_transit", label: "В работе" },
            { value: "received,closed", label: "Принятые и закрытые" },
            { value: "cancelled", label: "Отменённые" },
          ]}
        />
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={{ pageSize: 30, showSizeChanger: false }}
        scroll={{ x: 800 }}
        onRow={(r) => ({ onClick: () => nav(`/purchasing/orders/${r.id}`), style: { cursor: "pointer" } })}
        columns={[
          { title: "Номер", dataIndex: "number" },
          { title: "Поставщик", dataIndex: "supplier" },
          { title: "Дата заказа", dataIndex: "order_date", render: d },
          { title: "Поставка", dataIndex: "expected_date", render: d },
          { title: "Сумма", dataIndex: "total", align: "right", render: money },
          { title: "Статус", dataIndex: "status", render: (s, r) => <Tag color={ORDER_COLORS[s]}>{r.status_name}</Tag> },
          { title: "", dataIndex: "over_budget", render: (v) => (v ? <Tag color="orange">сверх бюджета</Tag> : null) },
        ]}
      />
    </>
  );
}

function Schedule() {
  const scenarios = useLoad<any[]>(() => api.get("/api/nsi/scenarios"));
  const [sid, setSid] = useState<number>();
  const { data } = useLoad<any>(() => (sid ? api.get(`/api/purchasing/scenarios/${sid}/schedule`) : Promise.resolve(null)), [sid]);
  return (
    <>
      <div className="toolbar">
        <Select placeholder="Сценарий праздника" style={{ minWidth: 300 }} value={sid} onChange={setSid} options={(scenarios.data || []).map((s) => ({ value: s.id, label: `${s.name} (${d(s.event_date)})` }))} />
        {data && (
          <Typography.Text type="secondary">
            Последняя поставка — {d(data.last_delivery_date)}, праздник — {d(data.event_date)}
          </Typography.Text>
        )}
      </div>
      {data && (
        <Table<any>
          rowKey="supplier_id"
          size="small"
          pagination={false}
          dataSource={data.suppliers}
          scroll={{ x: 700 }}
          columns={[
            { title: "Поставщик", dataIndex: "supplier" },
            { title: "Срок поставки", dataIndex: "lead_time_days", align: "right", render: (v) => `${v} дн.` },
            { title: "Последний день заказа", dataIndex: "last_order_date", render: (v, r) => (r.late ? <Tag color="red">{d(v)} — уже поздно</Tag> : d(v)) },
            { title: "Заказы по графику (заказ → поставка)", dataIndex: "orders", render: (os: any[]) => os.map((o) => `${dayjs(o.order_date).format("DD.MM")} → ${dayjs(o.delivery_date).format("DD.MM")}`).join(", ") || "—" },
          ]}
        />
      )}
    </>
  );
}
