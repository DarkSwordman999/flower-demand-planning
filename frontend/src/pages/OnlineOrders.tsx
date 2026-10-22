import { useState } from "react";
import { Button, DatePicker, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { d, dt, iso, money, num, ONLINE_COLORS } from "../format";

export default function OnlineOrders() {
  const { can } = useAuth();
  const [status, setStatus] = useState<string | undefined>();
  const [create, setCreate] = useState(false);
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/online-orders", { status }), [status]);
  const { busy, run } = useAction();

  const act = async (id: number, action: string, ok: string) => {
    if (await run(() => api.post(`/api/online-orders/${id}/${action}`), ok)) reload();
  };

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Заказы интернет-магазина
      </Typography.Title>
      <div className="toolbar">
        <Select
          placeholder="Все статусы"
          allowClear
          style={{ width: 200 }}
          value={status}
          onChange={setStatus}
          options={[
            { value: "new", label: "Новые" },
            { value: "preorder", label: "Предзаказы" },
            { value: "reserved", label: "Зарезервированы" },
            { value: "completed", label: "Выполнены" },
            { value: "cancelled", label: "Отменены" },
          ]}
        />
        <span className="spacer" />
        {can("shop_manager", "florist") && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreate(true)}>
            Заказ по телефону / предзаказ
          </Button>
        )}
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        scroll={{ x: 1000 }}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        expandable={{
          expandedRowRender: (o) => (
            <Table<any>
              rowKey="product_id"
              size="small"
              pagination={false}
              dataSource={o.lines}
              columns={[
                { title: "Товар", dataIndex: "product" },
                { title: "Кол-во", dataIndex: "qty", align: "right", render: (v) => num(v) },
                { title: "Цена", dataIndex: "price", align: "right", render: money },
              ]}
            />
          ),
        }}
        columns={[
          { title: "Номер", dataIndex: "external_id" },
          { title: "Создан", dataIndex: "created_at", render: dt },
          { title: "Доставка", dataIndex: "delivery_date", render: d },
          { title: "Покупатель", dataIndex: "customer_name" },
          { title: "Телефон", dataIndex: "phone" },
          { title: "Сумма", dataIndex: "total", align: "right", render: money },
          { title: "Статус", dataIndex: "status", render: (s, r) => <Tag color={ONLINE_COLORS[s]}>{r.status_name}</Tag> },
          {
            title: "",
            width: 280,
            render: (_, r) =>
              can("shop_manager") && (
                <Space>
                  {r.status === "preorder" && (
                    <Button size="small" loading={busy} onClick={() => act(r.id, "reserve", "Товар зарезервирован")}>
                      Резерв
                    </Button>
                  )}
                  {r.status === "reserved" && (
                    <Button size="small" type="primary" loading={busy} onClick={() => act(r.id, "complete", "Заказ выполнен — продажа проведена")}>
                      Выполнен
                    </Button>
                  )}
                  {!["completed", "cancelled"].includes(r.status) && (
                    <Popconfirm title="Отменить заказ и снять резерв?" onConfirm={() => act(r.id, "cancel", "Заказ отменён")}>
                      <Button size="small" danger>
                        Отменить
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
          },
        ]}
      />
      <CreateModal
        open={create}
        onClose={(ok) => {
          setCreate(false);
          if (ok) reload();
        }}
      />
    </>
  );
}

function CreateModal({ open, onClose }: { open: boolean; onClose: (ok: boolean) => void }) {
  const products = useRefs("products");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const submit = async () => {
    const v = await form.validateFields();
    const body = { ...v, id: v.id || `TEL-${dayjs().format("YYMMDDHHmmss")}`, delivery_date: iso(v.delivery_date) };
    if (await run(() => api.post("/api/online-orders", body), "Заказ принят")) {
      form.resetFields();
      onClose(true);
    }
  };
  return (
    <Modal open={open} title="Новый заказ покупателя" onCancel={() => onClose(false)} onOk={submit} okText="Принять" okButtonProps={{ loading: busy }} width={640} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false} initialValues={{ delivery_date: dayjs().add(1, "day"), allow_preorder: true, lines: [{}] }}>
        <Space wrap>
          <Form.Item name="customer_name" label="Покупатель" rules={[{ required: true }]}>
            <Input style={{ width: 240 }} />
          </Form.Item>
          <Form.Item name="phone" label="Телефон" rules={[{ required: true }]}>
            <Input style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="delivery_date" label="Дата доставки" rules={[{ required: true }]}>
            <DatePicker format="DD.MM.YYYY" disabledDate={(x) => x < dayjs().startOf("day")} />
          </Form.Item>
        </Space>
        <Form.List name="lines">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space key={f.key} align="baseline">
                  <Form.Item name={[f.name, "product_id"]} rules={[{ required: true, message: "Товар" }]}>
                    <Select showSearch optionFilterProp="label" placeholder="Товар" style={{ width: 340 }} options={products.map((p) => ({ value: p.id, label: p.name }))} />
                  </Form.Item>
                  <Form.Item name={[f.name, "qty"]} rules={[{ required: true, message: "Кол-во" }]}>
                    <InputNumber min={1} placeholder="Кол-во" />
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
        <Form.Item name="comment" label="Комментарий" style={{ marginTop: 12 }}>
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="allow_preorder" label="Если товара не хватает — оформить предзаказ" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
