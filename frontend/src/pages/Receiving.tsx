import { useRef, useState } from "react";
import { Alert, Button, Card, Checkbox, Empty, Input, InputNumber, List, Result, Space, Table, Tabs, Tag, Typography } from "antd";
import { BarcodeOutlined, DownloadOutlined, PrinterOutlined } from "@ant-design/icons";
import { api, download, openHtml } from "../api";
import { useAction, useLoad } from "../hooks";
import { d, dt, num } from "../format";

export default function Receiving() {
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Приёмка поставок
      </Typography.Title>
      <Tabs
        items={[
          { key: "r", label: "К приёмке", children: <ToReceive /> },
          { key: "a", label: "Акты расхождений", children: <Acts /> },
        ]}
      />
    </>
  );
}

interface LineState {
  received_qty: number;
  defect_qty: number;
  shelf_reduction_days: number;
  phyto_ok: boolean;
  quality: string;
}

function ToReceive() {
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/receiving/orders"));
  const [order, setOrder] = useState<any>(null);
  const [done, setDone] = useState<any>(null);

  if (done)
    return (
      <Result
        status={done.act_number ? "warning" : "success"}
        title={`Принято партий: ${done.batches.length}`}
        subTitle={
          (done.act_number ? `Есть расхождения — оформлен акт ${done.act_number}` : "Расхождений нет") +
          (done.reserved_preorders?.length ? `. Зарезервированы предзаказы: ${done.reserved_preorders.join(", ")}` : "")
        }
        extra={
          <Space wrap>
            {done.batches.length > 0 && (
              <Button icon={<PrinterOutlined />} type="primary" onClick={() => openHtml("/api/receiving/labels", { batch_ids: done.batches })}>
                Этикетки партий
              </Button>
            )}
            <Button
              onClick={() => {
                setDone(null);
                reload();
              }}
            >
              К списку поставок
            </Button>
          </Space>
        }
      >
        {done.act_lines.length > 0 && (
          <Table<any>
            size="small"
            rowKey={(_, i) => String(i)}
            pagination={false}
            dataSource={done.act_lines}
            columns={[
              { title: "Товар", dataIndex: "product" },
              { title: "Заказано", dataIndex: "ordered", align: "right" },
              { title: "Поступило", dataIndex: "received", align: "right" },
              { title: "Принято", dataIndex: "accepted", align: "right" },
              { title: "Причина", dataIndex: "reason" },
            ]}
          />
        )}
      </Result>
    );

  if (order)
    return (
      <ReceiveOrder
        order={order}
        onBack={() => setOrder(null)}
        onDone={(r) => {
          setOrder(null);
          setDone(r);
        }}
      />
    );

  return (
    <List
      loading={loading}
      locale={{ emptyText: <Empty description="Нет поставок в пути" /> }}
      grid={{ gutter: 12, xs: 1, sm: 2, lg: 3 }}
      dataSource={data || []}
      renderItem={(o: any) => (
        <List.Item>
          <Card
            hoverable
            onClick={() => setOrder(o)}
            title={o.number}
            extra={o.imported ? <Tag color="purple">импорт</Tag> : null}
          >
            <div>{o.supplier}</div>
            <div>Поставка: {d(o.expected_date)}</div>
            <div>Позиций: {o.lines.length}</div>
          </Card>
        </List.Item>
      )}
    />
  );
}

function ReceiveOrder({ order, onBack, onDone }: { order: any; onBack: () => void; onDone: (r: any) => void }) {
  const init = () =>
    Object.fromEntries(
      order.lines.map((l: any) => [l.id, { received_qty: 0, defect_qty: 0, shelf_reduction_days: 0, phyto_ok: false, quality: "" } as LineState]),
    );
  const [st, setSt] = useState<Record<number, LineState>>(init);
  const [scan, setScan] = useState("");
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const scanRef = useRef<any>(null);
  const { busy, run } = useAction();

  const set = (id: number, patch: Partial<LineState>) => setSt((s) => ({ ...s, [id]: { ...s[id], ...patch } }));

  const onScan = () => {
    const code = scan.trim();
    setScan("");
    const line = order.lines.find((l: any) => l.barcode === code);
    if (!line) {
      setMsg({ type: "error", text: `Штрихкод ${code} не найден в заказе` });
      return;
    }
    set(line.id, { received_qty: (st[line.id]?.received_qty || 0) + line.pack_multiple });
    setMsg({ type: "success", text: `${line.product}: +${line.pack_multiple}` });
    scanRef.current?.focus();
  };

  const allByOrder = () =>
    setSt((s) => Object.fromEntries(order.lines.map((l: any) => [l.id, { ...s[l.id], received_qty: l.ordered_qty, phyto_ok: s[l.id].phyto_ok || false }])));

  const submit = async () => {
    const items = order.lines.map((l: any) => ({ line_id: l.id, ...st[l.id] }));
    const r = await run(() => api.post(`/api/receiving/orders/${order.id}`, { items }));
    if (r) onDone(r);
  };

  return (
    <div className="tsd-card">
      <Space style={{ marginBottom: 12 }} wrap>
        <Button onClick={onBack}>← Назад</Button>
        <Typography.Text strong>
          {order.number} · {order.supplier}
        </Typography.Text>
      </Space>
      <Input
        ref={scanRef}
        size="large"
        autoFocus
        prefix={<BarcodeOutlined />}
        placeholder="Сканируйте штрихкод упаковки"
        value={scan}
        onChange={(e) => setScan(e.target.value)}
        onPressEnter={onScan}
        style={{ marginBottom: 8 }}
      />
      {msg && <Alert type={msg.type} message={msg.text} showIcon style={{ marginBottom: 8 }} />}
      <Button block onClick={allByOrder} style={{ marginBottom: 12 }}>
        Всё поступило по заказу
      </Button>
      {order.imported && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="Импорт: отметьте наличие фитосанитарных документов по каждой позиции — без них позиция не принимается." />}
      {order.lines.map((l: any) => {
        const s = st[l.id];
        const diff = l.ordered_qty ? Math.abs(s.received_qty - l.ordered_qty) / l.ordered_qty : 0;
        return (
          <Card key={l.id} size="small" style={{ marginBottom: 10 }} title={l.product} extra={<span>заказано {num(l.ordered_qty)}</span>}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <Space wrap>
                <span>Поступило</span>
                <InputNumber size="large" min={0} value={s.received_qty} onChange={(v) => set(l.id, { received_qty: Number(v) || 0 })} />
                {s.received_qty > 0 && diff > 0.02 && <Tag color="orange">расхождение {Math.round(diff * 100)} %</Tag>}
              </Space>
              <Space wrap>
                <span>Брак</span>
                <InputNumber min={0} max={s.received_qty} value={s.defect_qty} onChange={(v) => set(l.id, { defect_qty: Number(v) || 0 })} />
                <span>Сократить срок, дн.</span>
                <InputNumber min={0} max={30} value={s.shelf_reduction_days} onChange={(v) => set(l.id, { shelf_reduction_days: Number(v) || 0 })} />
              </Space>
              <Input placeholder="Качество (свежесть, длина стебля, повреждения)" value={s.quality} onChange={(e) => set(l.id, { quality: e.target.value })} />
              {order.imported && (
                <Checkbox checked={s.phyto_ok} onChange={(e) => set(l.id, { phyto_ok: e.target.checked })}>
                  Фитосанитарные документы есть
                </Checkbox>
              )}
            </Space>
          </Card>
        );
      })}
      <Button type="primary" size="large" block loading={busy} onClick={submit}>
        Завершить приёмку
      </Button>
    </div>
  );
}

function Acts() {
  const { data, loading } = useLoad<any[]>(() => api.get("/api/receiving/acts"));
  return (
    <Table<any>
      rowKey="id"
      size="small"
      loading={loading}
      dataSource={data || []}
      scroll={{ x: 700 }}
      expandable={{
        expandedRowRender: (a) => (
          <Table<any>
            size="small"
            rowKey={(_, i) => String(i)}
            pagination={false}
            dataSource={a.lines}
            columns={[
              { title: "Товар", dataIndex: "product" },
              { title: "Заказано", dataIndex: "ordered", align: "right" },
              { title: "Поступило", dataIndex: "received", align: "right" },
              { title: "Принято", dataIndex: "accepted", align: "right" },
              { title: "Расхождение", dataIndex: "diff", align: "right" },
              { title: "Причина", dataIndex: "reason" },
            ]}
          />
        ),
      }}
      columns={[
        { title: "Акт", dataIndex: "number" },
        { title: "Дата", dataIndex: "created_at", render: dt },
        { title: "Заказ", dataIndex: "order_number" },
        { title: "Поставщик", dataIndex: "supplier" },
        { title: "", width: 60, render: (_, a) => <Button size="small" icon={<DownloadOutlined />} onClick={() => download(`/api/receiving/acts/${a.id}/xlsx`)} /> },
      ]}
    />
  );
}
