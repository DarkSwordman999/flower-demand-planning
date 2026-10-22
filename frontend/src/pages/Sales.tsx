import { useState } from "react";
import { Alert, Button, DatePicker, Drawer, Form, InputNumber, Modal, Select, Space, Table, Tag, Typography, Upload } from "antd";
import { MinusCircleOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { dt, iso, money, num } from "../format";

const CHANNELS: Record<string, string> = { pos: "Касса", online: "Интернет-магазин", manual: "Продажа в системе" };

export default function Sales() {
  const { can, user } = useAuth();
  const locs = useRefs("locations");
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(6, "day"), dayjs()]);
  const [loc, setLoc] = useState<number | undefined>(user?.role === "florist" ? user.location_id ?? undefined : undefined);
  const [channel, setChannel] = useState<string | undefined>();
  const [detail, setDetail] = useState<any>(null);
  const [sale, setSale] = useState(false);
  const [imp, setImp] = useState<any>(null);
  const { data, loading, reload } = useLoad<any[]>(
    () => api.get("/api/sales", { date_from: iso(range[0]), date_to: iso(range[1]), location_id: loc, channel }),
    [range, loc, channel],
  );

  const upload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      setImp(await api.post("/api/sales/import", fd));
      reload();
    } catch (e: any) {
      setImp({ error: e.message });
    }
    return false;
  };

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Продажи
      </Typography.Title>
      <div className="toolbar">
        <DatePicker.RangePicker value={range} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])} format="DD.MM.YYYY" />
        <Select
          placeholder="Все точки"
          allowClear
          style={{ minWidth: 200 }}
          value={loc}
          onChange={setLoc}
          options={locs.filter((l) => l.type !== "warehouse").map((l) => ({ value: l.id, label: l.name }))}
        />
        <Select placeholder="Канал" allowClear style={{ width: 190 }} value={channel} onChange={setChannel} options={Object.entries(CHANNELS).map(([k, v]) => ({ value: k, label: v }))} />
        <span className="spacer" />
        {can("analyst", "storekeeper") && (
          <Upload accept=".csv,.json" showUploadList={false} beforeUpload={upload}>
            <Button icon={<UploadOutlined />}>Загрузить чеки «1С» (CSV/JSON)</Button>
          </Upload>
        )}
        {can("florist") && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setSale(true)}>
            Продажа
          </Button>
        )}
      </div>
      {imp &&
        (imp.error ? (
          <Alert type="error" closable onClose={() => setImp(null)} message={imp.error} style={{ marginBottom: 12 }} />
        ) : (
          <Alert
            type={imp.errors.length ? "warning" : "success"}
            closable
            onClose={() => setImp(null)}
            style={{ marginBottom: 12 }}
            message={`Загружено чеков: ${imp.created}, уже были загружены: ${imp.skipped}, с ошибками: ${imp.errors.length}`}
            description={imp.errors.length ? imp.errors.slice(0, 10).join("; ") : undefined}
          />
        ))}
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 800 }}
        onRow={(r) => ({ onClick: async () => setDetail(await api.get(`/api/sales/${r.id}`)), style: { cursor: "pointer" } })}
        columns={[
          { title: "Чек", dataIndex: "external_id", render: (v, r) => v || `№ ${r.id}` },
          { title: "Время", dataIndex: "ts", render: dt },
          { title: "Точка", dataIndex: "location" },
          { title: "Канал", dataIndex: "channel", render: (c) => <Tag>{CHANNELS[c] || c}</Tag> },
          { title: "Позиций", dataIndex: "items", align: "right" },
          { title: "Сумма, руб.", dataIndex: "total", align: "right", render: money },
        ]}
        summary={(rows) => (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={5}>
              <b>Итого</b>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={1} align="right">
              <b>{money(rows.reduce((s, r) => s + r.total, 0))}</b>
            </Table.Summary.Cell>
          </Table.Summary.Row>
        )}
      />
      <Drawer open={!!detail} onClose={() => setDetail(null)} width={560} title={detail && `Чек ${detail.external_id || detail.id}`}>
        {detail && (
          <>
            <p>
              {dt(detail.ts)} · {detail.location}
            </p>
            <Table<any>
              rowKey={(_, i) => String(i)}
              size="small"
              pagination={false}
              dataSource={detail.lines}
              columns={[
                { title: "Товар", dataIndex: "product" },
                { title: "Партия", dataIndex: "batch_id", render: (v) => v ?? <Tag color="red">нет в учёте</Tag> },
                { title: "Кол-во", dataIndex: "qty", align: "right", render: (v) => num(v) },
                { title: "Цена", dataIndex: "price", align: "right", render: money },
                { title: "Сумма", dataIndex: "sum", align: "right", render: money },
              ]}
            />
          </>
        )}
      </Drawer>
      <SaleModal
        open={sale}
        onClose={(ok) => {
          setSale(false);
          if (ok) reload();
        }}
      />
    </>
  );
}

function SaleModal({ open, onClose }: { open: boolean; onClose: (ok: boolean) => void }) {
  const { user } = useAuth();
  const locs = useRefs("locations");
  const products = useRefs("products");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const submit = async () => {
    const v = await form.validateFields();
    const r = await run(() => api.post("/api/sales", { location_id: v.location_id, lines: v.lines }), "Продажа проведена");
    if (r) {
      form.resetFields();
      onClose(true);
    }
  };
  return (
    <Modal open={open} title="Продажа в салоне" onCancel={() => onClose(false)} onOk={submit} okText="Провести" okButtonProps={{ loading: busy }} width={620} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false} initialValues={{ location_id: user?.location_id, lines: [{}] }}>
        <Form.Item name="location_id" label="Салон" rules={[{ required: true }]}>
          <Select options={locs.filter((l) => l.type !== "warehouse").map((l) => ({ value: l.id, label: l.name }))} />
        </Form.Item>
        <Form.List name="lines">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space key={f.key} align="baseline" wrap>
                  <Form.Item name={[f.name, "product_id"]} rules={[{ required: true, message: "Товар" }]}>
                    <Select showSearch optionFilterProp="label" placeholder="Товар" style={{ width: 300 }} options={products.map((p) => ({ value: p.id, label: `${p.name} — ${p.price} ₽` }))} />
                  </Form.Item>
                  <Form.Item name={[f.name, "qty"]} rules={[{ required: true, message: "Кол-во" }]}>
                    <InputNumber min={1} placeholder="Кол-во" />
                  </Form.Item>
                  <Form.Item name={[f.name, "discount"]}>
                    <InputNumber min={0} placeholder="Скидка, ₽" />
                  </Form.Item>
                  <MinusCircleOutlined onClick={() => remove(f.name)} />
                </Space>
              ))}
              <Button type="dashed" icon={<PlusOutlined />} onClick={() => add()} block>
                Добавить товар
              </Button>
            </>
          )}
        </Form.List>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          Товар списывается по FEFO — первой продаётся партия с ближайшим сроком; цена уценённой партии подставляется автоматически.
        </Typography.Paragraph>
      </Form>
    </Modal>
  );
}
