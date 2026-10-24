import { useState, type ReactNode } from "react";
import { Button, DatePicker, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { CheckOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { api } from "../api";
import { useAuth } from "../auth";
import { refreshRefs, useAction, useLoad, useRefs } from "../hooks";
import { d, money } from "../format";

interface Field {
  name: string;
  label: string;
  input: ReactNode;
  required?: boolean;
  bool?: boolean;
  date?: boolean;
  initial?: any;
}

/** Таблица справочника с формой добавления и изменения. */
function Crud(props: {
  url: string;
  refKey?: string;
  columns: any[];
  fields: Field[];
  roles: string[];
  title: string;
  extra?: (r: any, reload: () => void) => ReactNode;
  toBody?: (v: any) => any;
  toForm?: (r: any) => any;
  rowKey?: string;
}) {
  const { can } = useAuth();
  const { data, loading, reload } = useLoad<any[]>(() => api.get(props.url));
  const [edit, setEdit] = useState<any>(null);
  const [q, setQ] = useState("");
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const editable = can(...props.roles);

  const open = (r: any | null) => {
    const init: any = {};
    const src = r && props.toForm ? props.toForm(r) : r;
    props.fields.forEach((f) => {
      const v = src ? src[f.name] : f.initial;
      init[f.name] = f.date && v ? dayjs(v) : v;
    });
    form.setFieldsValue(init);
    setEdit(r || {});
  };
  const save = async () => {
    const v = await form.validateFields();
    props.fields.forEach((f) => {
      if (f.date && v[f.name]) v[f.name] = v[f.name].format("YYYY-MM-DD");
    });
    const body = props.toBody ? props.toBody(v) : v;
    const r = await run(() => (edit.id ? api.put(`${props.url}/${edit.id}`, body) : api.post(props.url, body)), "Сохранено");
    if (r) {
      setEdit(null);
      if (props.refKey) refreshRefs(props.refKey);
      reload();
    }
  };
  const rows = (data || []).filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="toolbar">
        <Input.Search placeholder="Поиск" allowClear onSearch={setQ} onChange={(e) => !e.target.value && setQ("")} style={{ width: 260 }} />
        <span className="spacer" />
        {editable && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>
            Добавить
          </Button>
        )}
      </div>
      <Table<any>
        rowKey={props.rowKey || "id"}
        size="small"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={[
          ...props.columns,
          {
            title: "",
            width: 110,
            render: (_: any, r: any) => (
              <Space>
                {editable && <Button size="small" icon={<EditOutlined />} onClick={() => open(r)} />}
                {props.extra?.(r, reload)}
              </Space>
            ),
          },
        ]}
      />
      <Modal open={!!edit} title={(edit?.id ? "Изменить: " : "Добавить: ") + props.title} onCancel={() => setEdit(null)} onOk={save} okText="Сохранить" okButtonProps={{ loading: busy }} width={620} forceRender>
        <Form form={form} layout="vertical">
          {props.fields.map((f) => (
            <Form.Item key={f.name} name={f.name} label={f.label} rules={f.required ? [{ required: true, message: "Обязательное поле" }] : undefined} valuePropName={f.bool ? "checked" : "value"}>
              {f.input}
            </Form.Item>
          ))}
        </Form>
      </Modal>
    </>
  );
}

const yesNo = (v: boolean) => (v ? <Tag color="green">да</Tag> : <Tag>нет</Tag>);

function GroupSelect() {
  const groups = useRefs("groups");
  return <Select options={groups.map((g) => ({ value: g.id, label: g.name }))} />;
}

function Products() {
  const groups = useRefs("groups");
  return (
    <Crud
      url="/api/nsi/products"
      refKey="products"
      title="товар"
      roles={["buyer", "analyst"]}
      columns={[
        { title: "Наименование", dataIndex: "name" },
        { title: "Группа", dataIndex: "group", filters: groups.map((g) => ({ text: g.name, value: g.name })), onFilter: (v: any, r: any) => r.group === v },
        { title: "Сорт", dataIndex: "variety" },
        { title: "Длина, см", dataIndex: "stem_length", align: "right" },
        { title: "Цвет", dataIndex: "color" },
        { title: "Срок, дн.", dataIndex: "shelf_life_days", align: "right" },
        { title: "Кратность", dataIndex: "pack_multiple", align: "right" },
        { title: "Цена", dataIndex: "price", align: "right", render: money },
        { title: "Штрихкод", dataIndex: "barcode" },
        { title: "Активен", dataIndex: "active", render: yesNo },
      ]}
      fields={[
        { name: "name", label: "Наименование", input: <Input />, required: true },
        { name: "group_id", label: "Товарная группа", input: <GroupSelect />, required: true },
        { name: "kind", label: "Вид", input: <Input /> },
        { name: "variety", label: "Сорт", input: <Input /> },
        { name: "stem_length", label: "Длина стебля, см", input: <InputNumber min={0} max={300} /> },
        { name: "color", label: "Цвет", input: <Input /> },
        { name: "unit", label: "Единица измерения", input: <Input />, initial: "шт" },
        { name: "shelf_life_days", label: "Срок реализации, дней", input: <InputNumber min={1} max={365} />, required: true, initial: 7 },
        { name: "pack_multiple", label: "Кратность упаковки", input: <InputNumber min={1} />, initial: 1 },
        { name: "price", label: "Розничная цена, руб.", input: <InputNumber min={0} step={10} />, required: true },
        { name: "barcode", label: "Штрихкод упаковки", input: <Input /> },
        { name: "active", label: "Активен", input: <Switch />, bool: true, initial: true },
      ]}
    />
  );
}

const WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

function Suppliers() {
  const [conds, setConds] = useState<any>(null);
  const methods = useLoad<any[]>(() => api.get("/api/nsi/order-methods"));
  return (
    <>
      <Crud
        url="/api/nsi/suppliers"
        refKey="suppliers"
        title="поставщик"
        roles={["buyer"]}
        columns={[
          { title: "Поставщик", dataIndex: "name" },
          { title: "Страна", dataIndex: "country", render: (v: string, r: any) => (r.imported ? <Tag color="purple">{v}</Tag> : v) },
          { title: "Срок поставки", dataIndex: "lead_time_days", align: "right", render: (v: number) => `${v} дн.` },
          { title: "Мин. сумма", dataIndex: "min_order_sum", align: "right", render: money },
          { title: "Дни заказа", dataIndex: "order_weekdays", render: (v: string) => v.split(",").map((x) => WD[Number(x)]).join(", ") },
          { title: "E-mail", dataIndex: "email" },
          { title: "Отправка заказа", dataIndex: "order_method_name" },
          { title: "Надёжность", dataIndex: "reliability", align: "right", render: (v: number) => `${Math.round(v * 100)} %` },
        ]}
        toBody={(v) => ({ ...v, order_weekdays: (v.order_weekdays || []).join(",") })}
        toForm={(r) => ({ ...r, order_weekdays: r.order_weekdays.split(",").filter(Boolean), order_api_key: "" })}
        fields={[
          { name: "name", label: "Наименование", input: <Input />, required: true },
          { name: "country", label: "Страна", input: <Input />, initial: "Россия" },
          { name: "lead_time_days", label: "Срок поставки, дней", input: <InputNumber min={0} max={60} />, required: true, initial: 1 },
          { name: "min_order_sum", label: "Минимальная сумма заказа, руб.", input: <InputNumber min={0} step={1000} />, initial: 0 },
          {
            name: "order_weekdays",
            label: "Дни формирования заказа",
            input: <Select mode="multiple" options={WD.map((w, i) => ({ value: String(i), label: w }))} />,
            required: true,
            initial: ["0", "3"],
          },
          { name: "email", label: "E-mail для заказов", input: <Input /> },
          {
            name: "order_method",
            label: "Способ отправки заказа",
            input: <Select options={(methods.data || []).map((m) => ({ value: m.code, label: m.name }))} />,
            required: true,
            initial: "email",
          },
          { name: "order_url", label: "Адрес API поставщика (для отправки через API)", input: <Input placeholder="https://…" />, initial: "" },
          { name: "order_api_key", label: "Ключ API поставщика (пусто — не менять)", input: <Input.Password autoComplete="new-password" />, initial: "" },
          { name: "reliability", label: "Доля поставок в срок (0–1)", input: <InputNumber min={0} max={1} step={0.01} />, initial: 0.95 },
          { name: "active", label: "Активен", input: <Switch />, bool: true, initial: true },
        ]}
        extra={(r) => (
          <Button size="small" onClick={() => setConds(r)}>
            Условия
          </Button>
        )}
      />
      <Drawer open={!!conds} onClose={() => setConds(null)} width={720} title={conds && `Условия поставки: ${conds.name}`} destroyOnClose>
        {conds && <Conditions supplier={conds} />}
      </Drawer>
    </>
  );
}

function Conditions({ supplier }: { supplier: any }) {
  const { can } = useAuth();
  const products = useRefs("products");
  const { data, reload } = useLoad<any[]>(() => api.get("/api/nsi/conditions", { supplier_id: supplier.id }));
  const [add, setAdd] = useState<any>({});
  const { busy, run } = useAction();
  const editable = can("buyer");
  return (
    <>
      {editable && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Select showSearch optionFilterProp="label" placeholder="Товар" style={{ width: 280 }} value={add.product_id} onChange={(v) => setAdd({ ...add, product_id: v })} options={products.map((p) => ({ value: p.id, label: p.name }))} />
          <InputNumber placeholder="Цена" min={0.01} value={add.price} onChange={(v) => setAdd({ ...add, price: v })} />
          <InputNumber placeholder="Кратность" min={1} value={add.pack_multiple} onChange={(v) => setAdd({ ...add, pack_multiple: v })} />
          <Button
            icon={<PlusOutlined />}
            loading={busy}
            onClick={async () => {
              if (await run(() => api.post("/api/nsi/conditions", { supplier_id: supplier.id, pack_multiple: 1, ...add }), "Условие добавлено")) {
                setAdd({});
                reload();
              }
            }}
          >
            Добавить
          </Button>
        </Space>
      )}
      <Table<any>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={data || []}
        columns={[
          { title: "Товар", dataIndex: "product" },
          { title: "Цена", dataIndex: "price", align: "right", render: money },
          { title: "Кратность", dataIndex: "pack_multiple", align: "right" },
          {
            title: "",
            width: 50,
            render: (_, c) =>
              editable && (
                <Popconfirm title="Удалить условие?" onConfirm={async () => (await run(() => api.del(`/api/nsi/conditions/${c.id}`))) && reload()}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
          },
        ]}
      />
    </>
  );
}

function Locations() {
  return (
    <Crud
      url="/api/nsi/locations"
      refKey="locations"
      title="место хранения"
      roles={["admin"]}
      columns={[
        { title: "Наименование", dataIndex: "name" },
        { title: "Тип", dataIndex: "type_name" },
        { title: "Активно", dataIndex: "active", render: yesNo },
      ]}
      fields={[
        { name: "name", label: "Наименование", input: <Input />, required: true },
        {
          name: "type",
          label: "Тип",
          input: <Select options={[{ value: "warehouse", label: "Склад" }, { value: "salon", label: "Салон" }, { value: "online", label: "Интернет-магазин" }]} />,
          required: true,
          initial: "salon",
        },
        { name: "active", label: "Активно", input: <Switch />, bool: true, initial: true },
      ]}
    />
  );
}

function Groups() {
  return (
    <Crud
      url="/api/nsi/groups"
      refKey="groups"
      title="товарная группа"
      roles={["buyer", "analyst"]}
      columns={[{ title: "Группа", dataIndex: "name" }]}
      fields={[{ name: "name", label: "Наименование", input: <Input />, required: true }]}
    />
  );
}

function Events() {
  const groups = useRefs("groups");
  return (
    <Crud
      url="/api/nsi/events"
      title="событие календаря"
      roles={["buyer", "analyst"]}
      columns={[
        { title: "Дата", dataIndex: "date", render: (v: string, r: any) => (r.recurring ? dayjs(v).format("DD.MM") + " ежегодно" : d(v)) },
        { title: "Событие", dataIndex: "name" },
        { title: "Тип", dataIndex: "type", render: (v: string) => (v === "promo" ? <Tag color="blue">акция</Tag> : <Tag color="magenta">праздник</Tag>) },
        { title: "Коэффициент спроса", dataIndex: "coefficient", align: "right", render: (v: number) => v ?? <Typography.Text type="secondary">по истории</Typography.Text> },
        { title: "Группа", dataIndex: "group_id", render: (v: number) => groups.find((g) => g.id === v)?.name || "все" },
      ]}
      fields={[
        { name: "date", label: "Дата", input: <DatePicker format="DD.MM.YYYY" />, required: true, date: true },
        { name: "name", label: "Название", input: <Input />, required: true },
        { name: "type", label: "Тип", input: <Select options={[{ value: "holiday", label: "Праздник" }, { value: "promo", label: "Акция" }]} />, initial: "holiday" },
        { name: "recurring", label: "Повторяется ежегодно", input: <Switch />, bool: true, initial: true },
        { name: "coefficient", label: "Коэффициент спроса (пусто — оценить по истории)", input: <InputNumber min={0.1} max={50} step={0.1} /> },
        { name: "group_id", label: "Только для группы (акция)", input: <Select allowClear options={groups.map((g) => ({ value: g.id, label: g.name }))} /> },
      ]}
      extra={(r, reload) => (
        <Popconfirm title="Удалить событие?" onConfirm={async () => (await api.del(`/api/nsi/events/${r.id}`), reload())}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      )}
    />
  );
}

function Scenarios() {
  const { can } = useAuth();
  const groups = useRefs("groups");
  const { run } = useAction();
  return (
    <Crud
      url="/api/nsi/scenarios"
      title="сценарий праздника"
      roles={["buyer", "director"]}
      columns={[
        { title: "Сценарий", dataIndex: "name" },
        { title: "Праздник", dataIndex: "event_date", render: d },
        { title: "Пик, дней до", dataIndex: "days_before", align: "right" },
        { title: "Последняя поставка", dataIndex: "last_delivery_date", render: d },
        {
          title: "Коэффициенты",
          dataIndex: "coefficients",
          render: (c: Record<string, number>) =>
            Object.entries(c || {})
              .map(([g, k]) => `${groups.find((x) => String(x.id) === g)?.name || g} ×${k}`)
              .join(", "),
        },
        { title: "Утверждён", dataIndex: "approved", render: yesNo },
      ]}
      toBody={(v) => ({
        ...v,
        coefficients: Object.fromEntries(groups.filter((g) => v[`k${g.id}`]).map((g) => [String(g.id), v[`k${g.id}`]])),
      })}
      toForm={(r) => ({ ...r, ...Object.fromEntries(Object.entries(r.coefficients || {}).map(([g, k]) => [`k${g}`, k])) })}
      fields={[
        { name: "name", label: "Название", input: <Input />, required: true },
        { name: "event_date", label: "Дата праздника", input: <DatePicker format="DD.MM.YYYY" />, required: true, date: true },
        { name: "days_before", label: "Пик начинается за, дней", input: <InputNumber min={0} max={14} />, initial: 2 },
        { name: "last_delivery_date", label: "Дата последней поставки", input: <DatePicker format="DD.MM.YYYY" />, required: true, date: true },
        ...groups.map((g) => ({ name: `k${g.id}`, label: `Коэффициент: ${g.name}`, input: <InputNumber min={0.1} max={50} step={0.1} /> })),
        { name: "comment", label: "Комментарий", input: <Input.TextArea rows={2} /> },
      ]}
      extra={(r, reload) =>
        can("buyer", "director") &&
        !r.approved && (
          <Button size="small" icon={<CheckOutlined />} title="Утвердить" onClick={async () => (await run(() => api.post(`/api/nsi/scenarios/${r.id}/approve`), "Сценарий утверждён")) && reload()} />
        )
      }
    />
  );
}

function Reasons() {
  return (
    <Crud
      url="/api/nsi/writeoff-reasons"
      refKey="writeoff-reasons"
      title="причина списания"
      roles={["admin"]}
      columns={[{ title: "Причина", dataIndex: "name" }]}
      fields={[{ name: "name", label: "Причина", input: <Input />, required: true }]}
    />
  );
}

export default function Nsi() {
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Справочники
      </Typography.Title>
      <Tabs
        items={[
          { key: "p", label: "Товары", children: <Products /> },
          { key: "g", label: "Группы", children: <Groups /> },
          { key: "s", label: "Поставщики", children: <Suppliers /> },
          { key: "l", label: "Места хранения", children: <Locations /> },
          { key: "e", label: "Календарь событий", children: <Events /> },
          { key: "h", label: "Сценарии праздников", children: <Scenarios /> },
          { key: "r", label: "Причины списания", children: <Reasons /> },
        ]}
      />
    </>
  );
}
