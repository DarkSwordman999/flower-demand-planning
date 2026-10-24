import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, Button, Card, Descriptions, Input, InputNumber, Modal, Popconfirm, Space, Spin, Table, Tag, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useSettings } from "../hooks";
import { d, dt, money, num, ORDER_COLORS } from "../format";
import { CalcPopover } from "./Purchasing";

const ACTIONS: Record<string, { label: string; roles: string[]; from: string[]; primary?: boolean; danger?: boolean; confirm?: string }> = {
  submit: { label: "На согласование", roles: ["buyer"], from: ["draft"], primary: true },
  approve: { label: "Утвердить", roles: ["director"], from: ["approval"], primary: true },
  reject: { label: "Вернуть на доработку", roles: ["director"], from: ["approval"] },
  send: { label: "Отправить поставщику", roles: ["buyer"], from: ["approved"], primary: true },
  confirm: { label: "Поставщик подтвердил", roles: ["buyer"], from: ["sent"] },
  in_transit: { label: "В пути", roles: ["buyer"], from: ["sent", "confirmed"] },
  close: { label: "Закрыть", roles: ["buyer"], from: ["received"] },
  cancel: { label: "Отменить", roles: ["buyer"], from: ["draft", "approval", "approved", "sent", "confirmed"], danger: true, confirm: "Отменить заказ?" },
};

export default function OrderCard() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: o, loading, setData } = useLoad<any>(() => api.get(`/api/purchasing/orders/${id}`), [id]);
  const [edit, setEdit] = useState<Record<number, { qty: number; reason: string }>>({});
  const { busy, run } = useAction();
  const [comment, setComment] = useState("");
  const limit = useSettings().change_reason_pct;

  useEffect(() => {
    if (o) setEdit(Object.fromEntries(o.lines.map((l: any) => [l.id, { qty: l.ordered_qty, reason: l.change_reason }])));
  }, [o]);

  if (loading && !o) return <Spin />;
  if (!o) return null;
  const draft = o.status === "draft" && can("buyer");
  const changed = o.lines.filter((l: any) => edit[l.id] && (edit[l.id].qty !== l.ordered_qty || edit[l.id].reason !== l.change_reason));
  const needReason = (l: any) => edit[l.id] && Math.abs(edit[l.id].qty - l.recommended_qty) / Math.max(l.recommended_qty, 1) * 100 > limit;

  const save = async () => {
    const items = changed.map((l: any) => ({ line_id: l.id, ordered_qty: edit[l.id].qty, change_reason: edit[l.id].reason }));
    const r = await run(() => api.put(`/api/purchasing/orders/${o.id}/lines`, { items }), "Изменения сохранены");
    if (r) setData(r);
  };
  const act = async (a: string) => {
    if (a === "reject" && !comment.trim()) {
      Modal.warning({ title: "Укажите причину возврата в комментарии" });
      return;
    }
    const r = await run(() => api.post(`/api/purchasing/orders/${o.id}/${a}`, { comment }), ACTIONS[a].label + " — выполнено");
    if (r) {
      setData(r);
      setComment("");
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Link to="/purchasing">← Заказы</Link>
      </Space>
      <Typography.Title level={3} className="page-title">
        Заказ {o.number} <Tag color={ORDER_COLORS[o.status]}>{o.status_name}</Tag>
        {o.over_budget && <Tag color="orange">сверх бюджета</Tag>}
      </Typography.Title>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Descriptions size="small" column={{ xs: 1, md: 3 }}>
          <Descriptions.Item label="Поставщик">{o.supplier}</Descriptions.Item>
          <Descriptions.Item label="E-mail">{o.supplier_email || "—"}</Descriptions.Item>
          <Descriptions.Item label="Склад">{o.location}</Descriptions.Item>
          <Descriptions.Item label="Дата заказа">{d(o.order_date)}</Descriptions.Item>
          <Descriptions.Item label="Поставка">{d(o.expected_date)}</Descriptions.Item>
          <Descriptions.Item label="Следующая поставка">{d(o.next_delivery_date)}</Descriptions.Item>
          <Descriptions.Item label="Сумма">
            <b>{money(o.total)}</b> руб.
          </Descriptions.Item>
          <Descriptions.Item label="Отправлен">{dt(o.sent_at)}</Descriptions.Item>
        </Descriptions>
        {o.comment && <pre style={{ whiteSpace: "pre-wrap", margin: "8px 0 0", fontFamily: "inherit" }}>{o.comment}</pre>}
      </Card>
      {o.warnings?.map((w: string) => (
        <Alert key={w} type="warning" showIcon message={w} style={{ marginBottom: 8 }} />
      ))}
      <Table<any>
        rowKey="id"
        size="small"
        dataSource={o.lines}
        pagination={false}
        scroll={{ x: 1000 }}
        columns={[
          { title: "Товар", dataIndex: "product" },
          { title: "Рекомендовано", dataIndex: "recommended_qty", width: 120, align: "right", render: (v) => num(v) },
          {
            title: "Заказано",
            width: 140,
            align: "right",
            render: (_, l) =>
              draft ? (
                <InputNumber min={0} step={l.pack_multiple} value={edit[l.id]?.qty} onChange={(v) => setEdit((s) => ({ ...s, [l.id]: { ...s[l.id], qty: Number(v) || 0 } }))} />
              ) : (
                num(l.ordered_qty)
              ),
          },
          { title: "Кратность", dataIndex: "pack_multiple", width: 90, align: "right" },
          { title: "Цена", dataIndex: "price", width: 90, align: "right", render: money },
          { title: "Сумма", width: 110, align: "right", render: (_, l) => money((draft ? edit[l.id]?.qty ?? l.ordered_qty : l.ordered_qty) * l.price) },
          {
            title: "Причина изменения",
            width: 240,
            render: (_, l) =>
              draft ? (
                <Input
                  placeholder={needReason(l) ? `обязательно: отклонение > ${limit} %` : ""}
                  status={needReason(l) && !edit[l.id]?.reason ? "error" : undefined}
                  value={edit[l.id]?.reason}
                  onChange={(e) => setEdit((s) => ({ ...s, [l.id]: { ...s[l.id], reason: e.target.value } }))}
                />
              ) : (
                l.change_reason
              ),
          },
          { title: "Принято", dataIndex: "received_qty", width: 90, align: "right", render: (v) => (v === null ? "" : num(v)) },
          { title: "", width: 80, render: (_, l) => <CalcPopover calc={l.calc} /> },
        ]}
      />
      <Space style={{ marginTop: 16 }} wrap>
        {draft && (
          <Button disabled={!changed.length} loading={busy} onClick={save}>
            Сохранить изменения
          </Button>
        )}
        {Object.entries(ACTIONS)
          .filter(([, a]) => a.from.includes(o.status) && can(...a.roles))
          .map(([k, a]) =>
            a.confirm ? (
              <Popconfirm key={k} title={a.confirm} onConfirm={() => act(k)}>
                <Button danger={a.danger} loading={busy}>
                  {a.label}
                </Button>
              </Popconfirm>
            ) : (
              <Button key={k} type={a.primary ? "primary" : "default"} danger={a.danger} loading={busy} disabled={k === "submit" && changed.length > 0} onClick={() => act(k)}>
                {a.label}
              </Button>
            ),
          )}
        <Button icon={<DownloadOutlined />} onClick={() => download(`/api/purchasing/orders/${o.id}/xlsx`)}>
          XLSX
        </Button>
      </Space>
      {(can("director") && o.status === "approval") || (can("buyer") && o.status !== "closed" && o.status !== "cancelled") ? (
        <Input.TextArea rows={2} placeholder="Комментарий к действию" style={{ marginTop: 12, maxWidth: 600 }} value={comment} onChange={(e) => setComment(e.target.value)} />
      ) : null}
    </>
  );
}
