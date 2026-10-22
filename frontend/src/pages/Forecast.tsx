import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Descriptions, Form, Input, InputNumber, Modal, Row, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { CartesianGrid, ComposedChart, Area, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart, Bar, ReferenceLine } from "recharts";
import dayjs from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { ALGORITHMS, d, dt, num, pct } from "../format";

export default function Forecast() {
  const { can } = useAuth();
  const [product, setProduct] = useState<number | undefined>();
  const status = useLoad<any>(() => api.get("/api/forecast/status"));
  const { busy, run } = useAction();

  const recalc = async () => {
    const r = await run(() => api.post("/api/forecast/run"));
    if (r) {
      Modal.success({ title: "Прогноз рассчитан", content: r.message });
      status.reload();
    }
  };

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Прогноз спроса
      </Typography.Title>
      <div className="toolbar">
        {status.data?.current && (
          <Typography.Text type="secondary">
            Действующий прогноз от {d(status.data.current.base_date)} · {status.data.current.message}
          </Typography.Text>
        )}
        <span className="spacer" />
        {can("analyst", "buyer") && (
          <Button type="primary" loading={busy} onClick={recalc}>
            Рассчитать сейчас
          </Button>
        )}
      </div>
      {status.data?.warning && <Alert type="warning" showIcon message={status.data.warning} style={{ marginBottom: 12 }} />}
      <Tabs
        items={[
          { key: "c", label: "График", children: <Chart product={product} setProduct={setProduct} key={status.data?.current?.id} /> },
          { key: "t", label: "Прогноз по товарам", children: <Horizon onPick={setProduct} key={status.data?.current?.id} /> },
          ...(can("analyst", "director") ? [{ key: "m", label: "Версии модели", children: <Models /> }] : []),
          { key: "w", label: "Погода", children: <Weather /> },
          { key: "r", label: "Журнал расчётов", children: <Runs key={status.data?.current?.id} /> },
        ]}
      />
    </>
  );
}

function Chart({ product, setProduct }: { product?: number; setProduct: (v?: number) => void }) {
  const products = useRefs("products");
  const locs = useRefs("locations");
  const [loc, setLoc] = useState<number | undefined>();
  useEffect(() => {
    if (!product && products.length) setProduct(products[0].id);
  }, [products, product, setProduct]);
  const { data } = useLoad<any>(() => (product ? api.get("/api/forecast/series", { product_id: product, location_id: loc, history: 70 }) : Promise.resolve(null)), [product, loc]);
  const points = (data?.points || []).map((p: any) => ({ ...p, band: p.p95 !== undefined ? [p.p50, p.p95] : undefined }));
  const today = data?.run?.base_date;

  return (
    <Card size="small">
      <div className="toolbar">
        <Select showSearch optionFilterProp="label" style={{ minWidth: 320 }} value={product} onChange={setProduct} options={products.map((p) => ({ value: p.id, label: p.name }))} />
        <Select
          placeholder="Все точки продаж"
          allowClear
          style={{ minWidth: 220 }}
          value={loc}
          onChange={setLoc}
          options={locs.filter((l) => l.type !== "warehouse").map((l) => ({ value: l.id, label: l.name }))}
        />
        {data?.algorithms?.length > 0 && <Typography.Text type="secondary">Модели: {data.algorithms.join(", ")}</Typography.Text>}
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart data={points}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="day" tickFormatter={(v) => dayjs(v).format("DD.MM")} minTickGap={16} />
          <YAxis width={50} />
          <Tooltip
            labelFormatter={(v) => dayjs(v).format("dd, DD.MM.YYYY")}
            formatter={(v: any, name: string) => (Array.isArray(v) ? [`${num(v[0])} – ${num(v[1])}`, name] : [num(v), name])}
          />
          <Legend />
          <Area dataKey="band" name="Интервал P50–P95" fill="#cfe6d6" stroke="none" />
          <Line dataKey="actual" name="Факт продаж" stroke="#555" dot={false} strokeWidth={1.5} />
          <Line dataKey="p50" name="Прогноз P50" stroke="#2f7a4f" dot={false} strokeWidth={2} />
          <Line dataKey="p80" name="P80" stroke="#d48806" dot={false} strokeDasharray="5 4" />
          {today && <ReferenceLine x={today} stroke="#999" label={{ value: "сегодня", position: "insideTopRight", fill: "#999" }} />}
        </ComposedChart>
      </ResponsiveContainer>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        P50 — медиана спроса; с вероятностью 80 % и 95 % спрос не превысит P80 и P95. Праздники учтены календарными коэффициентами, дни дефицита исключены из истории.
      </Typography.Paragraph>
    </Card>
  );
}

function Horizon({ onPick }: { onPick: (id: number) => void }) {
  const groups = useRefs("groups");
  const [group, setGroup] = useState<number | undefined>();
  const { data, loading } = useLoad<any>(() => api.get("/api/forecast/table", { group_id: group }), [group]);
  return (
    <>
      <div className="toolbar">
        <Select placeholder="Все группы" allowClear style={{ width: 240 }} value={group} onChange={setGroup} options={groups.map((g) => ({ value: g.id, label: g.name }))} />
      </div>
      <Table<any>
        rowKey="product_id"
        size="small"
        loading={loading}
        dataSource={data?.rows || []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 800 }}
        onRow={(r) => ({ onClick: () => onPick(r.product_id), style: { cursor: "pointer" } })}
        columns={[
          { title: "Товар", dataIndex: "product" },
          { title: "Группа", dataIndex: "group" },
          { title: "7 дней, P50", dataIndex: "week_p50", align: "right", render: (v) => num(v) },
          { title: "14 дней, P50", dataIndex: "p50", align: "right", render: (v) => num(v) },
          { title: "P80", dataIndex: "p80", align: "right", render: (v) => num(v) },
          { title: "P95", dataIndex: "p95", align: "right", render: (v) => num(v) },
          { title: "Модель", dataIndex: "algorithm" },
        ]}
      />
    </>
  );
}

function Models() {
  const { can } = useAuth();
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/forecast/models"));
  const groups = useRefs("groups");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const gname = (id: string) => groups.find((g) => String(g.id) === id)?.name || id;

  const create = async () => {
    const v = await form.validateFields();
    const m = await run(() => api.post("/api/forecast/models", v));
    if (m) {
      reload();
      Modal.info({
        title: `Версия ${m.version}: WAPE ${pct(m.wape * 100)}`,
        content: `Действующая версия на том же периоде: ${pct(m.details.published.wape * 100)}. ${
          m.wape <= m.details.published.wape ? "Новую версию можно опубликовать." : "Новая версия хуже — публикация будет отклонена."
        }`,
      });
    }
  };
  const publish = async (id: number) => {
    if (await run(() => api.post(`/api/forecast/models/${id}/publish`), "Версия опубликована")) reload();
    else reload();
  };

  return (
    <Row gutter={[16, 16]}>
      {can("analyst") && (
        <Col xs={24} lg={8}>
          <Card size="small" title="Пересчитать параметры модели">
            <Form form={form} layout="vertical" initialValues={{ algorithm: "auto", holdout: 28, trend: false, use_weather: true }}>
              <Form.Item name="algorithm" label="Алгоритм">
                <Select options={Object.entries(ALGORITHMS).map(([k, v]) => ({ value: k, label: v }))} />
              </Form.Item>
              <Form.Item name="holdout" label="Отложенный период, дней">
                <InputNumber min={14} max={56} step={7} />
              </Form.Item>
              <Form.Item name="trend" label="Тренд (затухающий) в модели Хольта–Уинтерса" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="use_weather" label="Учитывать погоду" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="comment" label="Комментарий">
                <Input />
              </Form.Item>
              <Button type="primary" loading={busy} onClick={create}>
                Оценить новую версию
              </Button>
            </Form>
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              Версия публикуется, только если её WAPE недельного прогноза по товарным группам на отложенном периоде не хуже действующей.
            </Typography.Paragraph>
          </Card>
        </Col>
      )}
      <Col xs={24} lg={can("analyst") ? 16 : 24}>
        <Table<any>
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={data || []}
          pagination={false}
          scroll={{ x: 700 }}
          expandable={{
            rowExpandable: (m) => !!m.details?.candidate?.groups,
            expandedRowRender: (m) => (
              <Descriptions size="small" column={1} bordered>
                {Object.entries(m.details.candidate.groups).map(([g, v]: any) => (
                  <Descriptions.Item key={g} label={gname(g)}>
                    WAPE {pct(v.wape !== null ? v.wape * 100 : null)} · факт {num(v.actual)} · прогноз {num(v.forecast)}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            ),
          }}
          columns={[
            { title: "Версия", dataIndex: "version", width: 80 },
            { title: "Алгоритм", dataIndex: "algorithm_name" },
            { title: "WAPE", dataIndex: "wape", align: "right", render: (v) => pct(v !== null ? v * 100 : null) },
            { title: "Смещение", dataIndex: "bias", align: "right", render: (v) => pct(v !== null ? v * 100 : null) },
            {
              title: "Статус",
              dataIndex: "status",
              render: (s, m) => <Tag color={{ published: "green", candidate: "blue", rejected: "red", archived: "default" }[s as string]}>{m.status_name}</Tag>,
            },
            { title: "Создана", dataIndex: "created_at", render: dt },
            { title: "Комментарий", dataIndex: "comment" },
            {
              title: "",
              render: (_, m) =>
                can("analyst") &&
                m.status === "candidate" && (
                  <Button size="small" type="primary" loading={busy} onClick={() => publish(m.id)}>
                    Опубликовать
                  </Button>
                ),
            },
          ]}
        />
      </Col>
    </Row>
  );
}

function Weather() {
  const { can } = useAuth();
  const { data, reload } = useLoad<any[]>(() => api.get("/api/forecast/weather"));
  const { busy, run } = useAction();
  const src: Record<string, string> = { "open-meteo": "Open-Meteo", climate: "климатическая норма", demo: "демо" };
  return (
    <Card size="small">
      <div className="toolbar">
        <Typography.Text type="secondary">Прогноз температуры на 14 дней и климатическая норма</Typography.Text>
        <span className="spacer" />
        {can("analyst") && (
          <Button loading={busy} onClick={async () => (await run(() => api.post("/api/forecast/weather/refresh"), "Погода обновлена")) && reload()}>
            Обновить прогноз погоды
          </Button>
        )}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data || []}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="day" tickFormatter={(v) => dayjs(v).format("DD.MM")} />
          <YAxis unit="°" width={40} />
          <Tooltip labelFormatter={(v) => d(v)} formatter={(v: number, n: string) => [`${num(v)} °C`, n]} />
          <Legend />
          <Bar dataKey="temp" name="Температура" fill="#69b1ff" />
          <Bar dataKey="normal" name="Норма" fill="#d9d9d9" />
        </BarChart>
      </ResponsiveContainer>
      <Space wrap>
        {Array.from(new Set((data || []).map((x) => x.source))).map((s) => (
          <Tag key={s as string}>{src[s as string] || (s as string)}</Tag>
        ))}
      </Space>
    </Card>
  );
}

function Runs() {
  const { data, loading } = useLoad<any[]>(() => api.get("/api/forecast/runs"));
  return (
    <Table<any>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={data || []}
      pagination={false}
      scroll={{ x: 800 }}
      columns={[
        { title: "Расчёт", dataIndex: "id", width: 70 },
        { title: "Начат", dataIndex: "started_at", render: dt },
        { title: "Прогноз с", dataIndex: "base_date", render: d },
        { title: "Запуск", dataIndex: "trigger", render: (t) => (t === "schedule" ? "по расписанию" : "вручную") },
        { title: "Статус", dataIndex: "status", render: (s) => <Tag color={s === "ok" ? "green" : s === "failed" ? "red" : "blue"}>{s === "ok" ? "готов" : s === "failed" ? "ошибка" : "идёт"}</Tag> },
        { title: "Результат", dataIndex: "message" },
      ]}
    />
  );
}
