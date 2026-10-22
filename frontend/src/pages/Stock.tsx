import { useState } from "react";
import { Button, Drawer, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Typography } from "antd";
import { DownloadOutlined, SwapOutlined } from "@ant-design/icons";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { BATCH_STATES, d, dt, money, num } from "../format";

export default function Stock() {
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Запасы и партии
      </Typography.Title>
      <Tabs
        items={[
          { key: "b", label: "Партии", children: <Batches /> },
          { key: "s", label: "Сводка остатков", children: <Summary /> },
          { key: "w", label: "Акты списания", children: <Acts /> },
        ]}
      />
    </>
  );
}

function LocationSelect(props: { value?: number; onChange?: (v?: number) => void; allowClear?: boolean; style?: any }) {
  const locs = useRefs("locations");
  return (
    <Select
      placeholder="Место хранения"
      style={{ minWidth: 200, ...props.style }}
      allowClear={props.allowClear}
      value={props.value}
      onChange={props.onChange}
      options={locs.map((l) => ({ value: l.id, label: l.name }))}
    />
  );
}

function Batches() {
  const { user, can } = useAuth();
  const [loc, setLoc] = useState<number | undefined>(user?.role === "florist" ? user.location_id ?? undefined : undefined);
  const [state, setState] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<any[]>([]);
  const [moves, setMoves] = useState<any>(null);
  const [mode, setMode] = useState<"" | "writeoff" | "count" | "transfer">("");
  const { data, loading, reload } = useLoad(() => api.get("/api/inventory/batches", { location_id: loc, state, q }), [loc, state, q]);

  const showMoves = async (b: any) => setMoves({ batch: b, rows: await api.get(`/api/inventory/batches/${b.id}/moves`) });

  return (
    <>
      <div className="toolbar">
        <LocationSelect value={loc} onChange={setLoc} allowClear />
        <Select
          placeholder="Состояние"
          allowClear
          style={{ width: 170 }}
          value={state}
          onChange={setState}
          options={Object.entries(BATCH_STATES)
            .slice(0, 4)
            .map(([k, v]) => ({ value: k, label: v[0] }))}
        />
        <Input.Search placeholder="Товар или штрихкод" allowClear onSearch={setQ} style={{ width: 240 }} />
        <span className="spacer" />
        {can("storekeeper", "florist") && (
          <Button danger disabled={!sel.length} onClick={() => setMode("writeoff")}>
            Списать ({sel.length})
          </Button>
        )}
        {can("storekeeper") && (
          <>
            <Button disabled={!sel.length} onClick={() => setMode("count")}>
              Инвентаризация ({sel.length})
            </Button>
            <Button icon={<SwapOutlined />} onClick={() => setMode("transfer")}>
              Переместить
            </Button>
          </>
        )}
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        scroll={{ x: 1000 }}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        rowSelection={can("storekeeper", "florist") ? { selectedRowKeys: sel.map((x) => x.id), onChange: (_, rows) => setSel(rows) } : undefined}
        rowClassName={(r) => (r.state === "expired" ? "row-bad" : r.state === "expiring" ? "row-warn" : "")}
        columns={[
          { title: "Партия", dataIndex: "id", width: 80, render: (v, r) => <a onClick={() => showMoves(r)}>{v}</a> },
          { title: "Товар", dataIndex: "product" },
          { title: "Место", dataIndex: "location", width: 170 },
          { title: "Поступила", dataIndex: "received_at", width: 105, render: d },
          { title: "Годен до", dataIndex: "expiry_date", width: 105, render: d, sorter: (a, b) => a.expiry_date.localeCompare(b.expiry_date) },
          { title: "Дней", dataIndex: "days_left", width: 65, align: "right" },
          { title: "Остаток", dataIndex: "qty", width: 85, align: "right", render: (v) => num(v) },
          { title: "Резерв", dataIndex: "reserved", width: 80, align: "right", render: (v) => (v ? num(v) : "") },
          { title: "Цена", dataIndex: "sale_price", width: 95, align: "right", render: money },
          {
            title: "Состояние",
            dataIndex: "state",
            width: 135,
            render: (s, r) => (
              <Tag color={BATCH_STATES[s]?.[1]}>
                {BATCH_STATES[s]?.[0]}
                {r.discount_pct ? ` −${r.discount_pct}%` : ""}
              </Tag>
            ),
          },
        ]}
      />
      <WriteOffModal
        open={mode === "writeoff"}
        batches={sel}
        onClose={(ok) => {
          setMode("");
          if (ok) {
            setSel([]);
            reload();
          }
        }}
      />
      <CountModal
        open={mode === "count"}
        batches={sel}
        onClose={(ok) => {
          setMode("");
          if (ok) {
            setSel([]);
            reload();
          }
        }}
      />
      <TransferModal
        open={mode === "transfer"}
        onClose={(ok) => {
          setMode("");
          if (ok) reload();
        }}
      />
      <Drawer open={!!moves} onClose={() => setMoves(null)} width={520} title={moves && `Партия ${moves.batch.id}: ${moves.batch.product}`}>
        {moves && (
          <Table<any>
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            dataSource={moves.rows}
            columns={[
              { title: "Когда", dataIndex: "ts", render: dt },
              { title: "Операция", dataIndex: "kind", render: (k) => MOVE_KINDS[k] || k },
              { title: "Кол-во", dataIndex: "qty", align: "right", render: (v) => num(v) },
              { title: "Основание", dataIndex: "ref" },
            ]}
          />
        )}
      </Drawer>
    </>
  );
}

const MOVE_KINDS: Record<string, string> = {
  receipt: "Приход",
  sale: "Продажа",
  writeoff: "Списание",
  transfer_out: "Перемещение (расход)",
  transfer_in: "Перемещение (приход)",
  inventory: "Инвентаризация",
  return: "Возврат",
};

export function WriteOffModal({ open, batches, onClose }: { open: boolean; batches: any[]; onClose: (ok: boolean) => void }) {
  const reasons = useRefs("writeoff-reasons");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const submit = async () => {
    const v = await form.validateFields();
    const items = batches.map((b) => ({ batch_id: b.id, qty: v[`q${b.id}`] }));
    const r = await run(() => api.post("/api/inventory/writeoff", { items, reason_id: v.reason_id, comment: v.comment || "" }));
    if (r) {
      Modal.success({
        title: `Оформлен акт ${r.act_number}`,
        content: "Акт можно выгрузить на вкладке «Акты списания».",
      });
      form.resetFields();
      onClose(true);
    }
  };
  return (
    <Modal open={open} title="Списание товара" onCancel={() => onClose(false)} onOk={submit} okText="Списать" okButtonProps={{ danger: true, loading: busy }} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="reason_id" label="Причина" rules={[{ required: true, message: "Выберите причину" }]}>
          <Select options={reasons.map((r) => ({ value: r.id, label: r.name }))} />
        </Form.Item>
        {batches.map((b) => (
          <Form.Item key={b.id} name={`q${b.id}`} label={`${b.product} (партия ${b.id}, доступно ${num(b.available)})`} initialValue={b.available} rules={[{ required: true }]}>
            <InputNumber min={0.001} max={b.available} style={{ width: "100%" }} />
          </Form.Item>
        ))}
        <Form.Item name="comment" label="Комментарий">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function CountModal({ open, batches, onClose }: { open: boolean; batches: any[]; onClose: (ok: boolean) => void }) {
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const submit = async () => {
    const v = await form.validateFields();
    const r = await run(() => api.post("/api/inventory/count", { items: batches.map((b) => ({ batch_id: b.id, qty: v[`q${b.id}`] })) }));
    if (r) {
      Modal.info({ title: "Инвентаризация проведена", content: `Расхождений: ${r.differences.length}` });
      onClose(true);
    }
  };
  return (
    <Modal open={open} title="Инвентаризация: фактическое количество" onCancel={() => onClose(false)} onOk={submit} okText="Провести" okButtonProps={{ loading: busy }} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        {batches.map((b) => (
          <Form.Item key={b.id} name={`q${b.id}`} label={`${b.product} — партия ${b.id}, ${b.location} (по учёту ${num(b.qty)})`} initialValue={b.qty} rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}

function TransferModal({ open, onClose }: { open: boolean; onClose: (ok: boolean) => void }) {
  const products = useRefs("products");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const submit = async () => {
    const v = await form.validateFields();
    const r = await run(() => api.post("/api/inventory/transfer", v), "Товар перемещён");
    if (r) onClose(true);
  };
  return (
    <Modal open={open} title="Перемещение товара (по FEFO)" onCancel={() => onClose(false)} onOk={submit} okText="Переместить" okButtonProps={{ loading: busy }} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="product_id" label="Товар" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" options={products.map((p) => ({ value: p.id, label: p.name }))} />
        </Form.Item>
        <Space style={{ display: "flex" }} wrap>
          <Form.Item name="from_location_id" label="Откуда" rules={[{ required: true }]}>
            <LocationSelect />
          </Form.Item>
          <Form.Item name="to_location_id" label="Куда" rules={[{ required: true }]}>
            <LocationSelect />
          </Form.Item>
        </Space>
        <Form.Item name="qty" label="Количество" rules={[{ required: true }]}>
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function Summary() {
  const [loc, setLoc] = useState<number | undefined>();
  const { data, loading } = useLoad(() => api.get("/api/inventory/stock", { location_id: loc }), [loc]);
  return (
    <>
      <div className="toolbar">
        <LocationSelect value={loc} onChange={setLoc} allowClear />
      </div>
      <Table<any>
        rowKey={(r) => `${r.product_id}-${r.location_id}`}
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={[
          { title: "Товар", dataIndex: "product" },
          { title: "Место", dataIndex: "location" },
          { title: "Всего", dataIndex: "qty", align: "right", render: (v) => num(v) },
          { title: "Доступно", dataIndex: "available", align: "right", render: (v) => num(v) },
          { title: "Резерв", dataIndex: "reserved", align: "right", render: (v) => num(v) },
          { title: "Срок истекает", dataIndex: "expiring", align: "right", render: (v) => (v ? <Tag color="orange">{num(v)}</Tag> : "") },
          { title: "Просрочено", dataIndex: "expired", align: "right", render: (v) => (v ? <Tag color="red">{num(v)}</Tag> : "") },
          { title: "Ближайший срок", dataIndex: "nearest_expiry", render: d },
          { title: "Стоимость, руб.", dataIndex: "value", align: "right", render: money },
        ]}
      />
    </>
  );
}

function Acts() {
  const { data, loading } = useLoad(() => api.get("/api/inventory/writeoffs"));
  const [act, setAct] = useState<any>(null);
  return (
    <>
      <Table<any>
        rowKey="act_number"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={{ pageSize: 30, showSizeChanger: false }}
        scroll={{ x: 800 }}
        columns={[
          { title: "Акт", dataIndex: "act_number", render: (v) => <a onClick={async () => setAct(await api.get(`/api/inventory/writeoffs/${encodeURIComponent(v)}`))}>{v}</a> },
          { title: "Дата", dataIndex: "ts", render: dt },
          { title: "Причина", dataIndex: "reason" },
          { title: "Место", dataIndex: "location" },
          { title: "Количество", dataIndex: "qty", align: "right", render: (v) => num(v) },
          { title: "Сумма, руб.", dataIndex: "cost", align: "right", render: money },
          {
            title: "",
            width: 60,
            render: (_, r) => <Button size="small" icon={<DownloadOutlined />} onClick={() => download(`/api/inventory/writeoffs/${encodeURIComponent(r.act_number)}/xlsx`)} />,
          },
        ]}
      />
      <Modal open={!!act} onCancel={() => setAct(null)} footer={null} width={720} title={act && `Акт списания ${act.act_number}`}>
        {act && (
          <>
            <p>
              {dt(act.ts)} · {act.reason}
              {act.comment ? ` · ${act.comment}` : ""}
            </p>
            <Table<any>
              rowKey="batch_id"
              size="small"
              pagination={false}
              dataSource={act.items}
              columns={[
                { title: "Товар", dataIndex: "product" },
                { title: "Партия", dataIndex: "batch_id" },
                { title: "Годен до", dataIndex: "expiry_date", render: d },
                { title: "Кол-во", dataIndex: "qty", align: "right", render: (v) => num(v) },
                { title: "Сумма", dataIndex: "sum", align: "right", render: money },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  );
}
