import { useEffect, useState } from "react";
import { App, Button, Card, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { DownloadOutlined, PlusOutlined } from "@ant-design/icons";
import type { Dayjs } from "dayjs";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs } from "../hooks";
import { dt, iso } from "../format";

export default function Admin() {
  const { can } = useAuth();
  const tabs = [
    ...(can("admin") ? [{ key: "u", label: "Пользователи", children: <Users /> }] : []),
    ...(can("admin") ? [{ key: "c", label: "Каналы продаж", children: <Channels /> }] : []),
    { key: "s", label: "Параметры", children: <Settings /> },
    ...(can("director") ? [{ key: "a", label: "Журнал действий", children: <Audit /> }] : []),
    ...(can("analyst", "director") ? [{ key: "i", label: "Обмен и расписание", children: <Integration /> }] : []),
    ...(can("admin") ? [{ key: "b", label: "Резервные копии", children: <Backups /> }] : []),
  ];
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Администрирование
      </Typography.Title>
      <Tabs items={tabs} />
    </>
  );
}

function Users() {
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/admin/users"));
  const roles = useLoad<any[]>(() => api.get("/api/admin/roles"));
  const locs = useRefs("locations");
  const [edit, setEdit] = useState<any>(null);
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const open = (u: any) => {
    form.setFieldsValue(u ? { ...u, password: "" } : { active: true, role: "florist", password: "" });
    setEdit(u || {});
  };
  const save = async () => {
    const v = await form.validateFields();
    if (!v.password) delete v.password;
    const r = await run(() => (edit.id ? api.put(`/api/admin/users/${edit.id}`, v) : api.post("/api/admin/users", v)), "Сохранено");
    if (r) {
      setEdit(null);
      reload();
    }
  };
  return (
    <>
      <div className="toolbar">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>
          Добавить пользователя
        </Button>
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={false}
        onRow={(u) => ({ onClick: () => open(u), style: { cursor: "pointer" } })}
        columns={[
          { title: "Логин", dataIndex: "login" },
          { title: "ФИО", dataIndex: "full_name" },
          { title: "Роль", dataIndex: "role_name" },
          { title: "Салон", dataIndex: "location_id", render: (v) => locs.find((l) => l.id === v)?.name || "" },
          { title: "Активен", dataIndex: "active", render: (v) => (v === false ? <Tag color="red">заблокирован</Tag> : <Tag color="green">да</Tag>) },
        ]}
      />
      <Modal open={!!edit} title={edit?.id ? "Пользователь" : "Новый пользователь"} onCancel={() => setEdit(null)} onOk={save} okButtonProps={{ loading: busy }} okText="Сохранить" forceRender>
        <Form form={form} layout="vertical">
          <Form.Item name="login" label="Логин" rules={[{ required: true, min: 2 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="full_name" label="ФИО" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="Роль" rules={[{ required: true }]}>
            <Select options={(roles.data || []).map((r) => ({ value: r.code, label: r.name }))} />
          </Form.Item>
          <Form.Item name="location_id" label="Салон (для продавца-флориста)">
            <Select allowClear options={locs.map((l) => ({ value: l.id, label: l.name }))} />
          </Form.Item>
          <Form.Item name="password" label={edit?.id ? "Новый пароль (пусто — не менять)" : "Пароль"} rules={edit?.id ? [] : [{ required: true, min: 6, message: "Не короче 6 символов" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="active" label="Активен" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}


/** Каналы продаж (Р-4): маркетплейсы и другие сайты подключаются к API интернет-магазина со своим ключом. */
function Channels() {
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/admin/channels"));
  const locs = useRefs("locations");
  const [edit, setEdit] = useState<any>(null);
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const { modal } = App.useApp();
  const showKey = (c: any) =>
    modal.info({
      title: `Ключ API канала «${c.name}»`,
      width: 560,
      content: (
        <>
          <Typography.Paragraph>Передайте ключ площадке: заголовок <code>X-API-Key</code> в запросах к <code>/api/shop/…</code>. Ключ показывается один раз — сохраните его.</Typography.Paragraph>
          <Typography.Paragraph copyable code>
            {c.api_key}
          </Typography.Paragraph>
        </>
      ),
    });
  const open = (c: any) => {
    form.setFieldsValue(c || { active: true, price_factor: 1 });
    setEdit(c || {});
  };
  const save = async () => {
    const v = await form.validateFields();
    const r = await run(() => (edit.id ? api.put(`/api/admin/channels/${edit.id}`, v) : api.post("/api/admin/channels", v)), "Сохранено");
    if (r) {
      setEdit(null);
      reload();
      if ((r as any).api_key) showKey(r);
    }
  };
  const rotate = () =>
    modal.confirm({
      title: "Выдать новый ключ?",
      content: "Старый ключ сразу перестанет действовать — площадку нужно перенастроить.",
      okText: "Выдать",
      onOk: async () => {
        const r = await run(() => api.post(`/api/admin/channels/${edit.id}/key`));
        if (r) {
          setEdit(null);
          showKey(r);
        }
      },
    });
  return (
    <>
      <div className="toolbar">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>
          Подключить канал
        </Button>
        <Typography.Text type="secondary">Основной сайт работает с ключом из настроек сервера (FLORAPLAN_SHOP_API_KEY).</Typography.Text>
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={false}
        onRow={(c) => ({ onClick: () => open(c), style: { cursor: "pointer" } })}
        columns={[
          { title: "Канал", dataIndex: "name" },
          { title: "Код (префикс заказов)", dataIndex: "code" },
          { title: "Остатки и резерв", dataIndex: "location" },
          { title: "Коэффициент цены", dataIndex: "price_factor", align: "right" },
          { title: "Подключён", dataIndex: "created_at", render: dt },
          { title: "Активен", dataIndex: "active", render: (v) => (v ? <Tag color="green">да</Tag> : <Tag color="red">отключён</Tag>) },
        ]}
      />
      <Modal open={!!edit} title={edit?.id ? "Канал продаж" : "Новый канал продаж"} onCancel={() => setEdit(null)} onOk={save} okButtonProps={{ loading: busy }} okText="Сохранить" forceRender
        footer={(orig) => (
          <Space>
            {edit?.id && <Button onClick={rotate}>Новый ключ API</Button>}
            {orig}
          </Space>
        )}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="Название" rules={[{ required: true }]}>
            <Input placeholder="Ozon" />
          </Form.Item>
          <Form.Item name="code" label="Код — строчная латиница, цифры, «-», «_»" rules={[{ required: true, pattern: /^[a-z0-9_-]{2,30}$/, message: "2–30 символов: a–z, 0–9, - и _" }]}>
            <Input placeholder="ozon" />
          </Form.Item>
          <Form.Item name="location_id" label="Место хранения: остатки и резерв заказов" rules={[{ required: true }]}>
            <Select options={locs.map((l) => ({ value: l.id, label: l.name }))} />
          </Form.Item>
          <Form.Item name="price_factor" label="Коэффициент цены (цена канала = розничная × коэффициент)" rules={[{ required: true }]}>
            <InputNumber min={0.1} max={10} step={0.05} />
          </Form.Item>
          <Form.Item name="active" label="Активен" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

const SETTINGS: [string, string, "number" | "text" | "share", number?, number?, number?][] = [
  ["company_name", "Название организации (в документах)", "text"],
  ["weekly_budget", "Бюджет закупок на неделю, руб. (П-8)", "number", 0, undefined, 10000],
  ["expiring_days", "«Срок истекает» — дней до «годен до» (С-12)", "number", 0, 14, 1],
  ["markdown_min", "Минимальная уценка, %", "number", 1, 100, 5],
  ["markdown_max", "Максимальная уценка, %", "number", 1, 100, 5],
  ["discrepancy_pct", "Акт расхождений при отклонении больше, % (С-2)", "number", 0, 100, 0.5],
  ["change_reason_pct", "Причина при изменении рекомендации больше, % (С-10)", "number", 0, 100, 5],
  ["forecast_horizon", "Горизонт прогноза, дней (С-6)", "number", 7, 60, 1],
  ["forecast_hour", "Час ежедневного расчёта прогноза (С-6)", "number", 0, 23, 1],
  ["history_days", "Глубина истории для прогноза, дней", "number", 90, 1500, 30],
  ["service_level_min", "Уровень обслуживания α: не ниже", "share", 0.5, 0.99, 0.01],
  ["service_level_max", "Уровень обслуживания α: не выше", "share", 0.5, 0.995, 0.01],
  ["salvage_share", "Доля себестоимости, возвращаемая при списании", "share", 0, 1, 0.05],
  ["pd_retention_days", "Обезличивать данные покупателей в закрытых онлайн-заказах через, дней (152-ФЗ)", "number", 30, 3650, 30],
];

function Settings() {
  const { can } = useAuth();
  const { data, reload } = useLoad<any>(() => api.get("/api/admin/settings"));
  const [form] = Form.useForm();
  const { busy, run } = useAction();
  const editable = can("director");
  useEffect(() => {
    if (data) form.setFieldsValue(data);
  }, [data, form]);
  const save = async () => {
    const v = await form.validateFields();
    if (await run(() => api.put("/api/admin/settings", v), "Параметры сохранены")) reload();
  };
  return (
    <Card size="small" style={{ maxWidth: 720 }}>
      <Form form={form} layout="horizontal" labelCol={{ span: 14 }} wrapperCol={{ span: 10 }} disabled={!editable}>
        {SETTINGS.map(([k, label, type, min, max, step]) => (
          <Form.Item key={k} name={k} label={label} rules={[{ required: true }]}>
            {type === "text" ? <Input /> : <InputNumber min={min} max={max} step={step} style={{ width: "100%" }} />}
          </Form.Item>
        ))}
        {editable && (
          <Button type="primary" loading={busy} onClick={save}>
            Сохранить
          </Button>
        )}
      </Form>
    </Card>
  );
}

function Audit() {
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [q, setQ] = useState("");
  const { data, loading } = useLoad<any[]>(() => api.get("/api/admin/audit", { date_from: iso(range?.[0]), date_to: iso(range?.[1]), q }), [range, q]);
  return (
    <>
      <div className="toolbar">
        <DatePicker.RangePicker format="DD.MM.YYYY" value={range} onChange={(v) => setRange(v as any)} />
        <Input.Search placeholder="Пользователь, действие, подробности" allowClear onSearch={setQ} style={{ width: 320 }} />
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 900 }}
        columns={[
          { title: "Время", dataIndex: "ts", width: 150, render: dt },
          { title: "Пользователь", dataIndex: "user", width: 130 },
          { title: "Действие", dataIndex: "action", width: 260 },
          { title: "Объект", width: 160, render: (_, r) => (r.entity ? `${r.entity} ${r.entity_id}` : "") },
          { title: "Подробности", dataIndex: "details" },
        ]}
      />
    </>
  );
}

function Integration() {
  const { can } = useAuth();
  const [system, setSystem] = useState<string | undefined>();
  const log = useLoad<any[]>(() => api.get("/api/admin/integration-log", { system }), [system]);
  const jobs = useLoad<any>(() => api.get("/api/admin/jobs"));
  const { busy, run } = useAction();
  const SYS: Record<string, string> = { "1c": "«1С» и кассы", shop: "Интернет-магазин", weather: "Погода", scheduler: "Планировщик", forecast: "Прогноз" };
  return (
    <>
      <Card size="small" title="Задачи по расписанию" style={{ marginBottom: 12 }}>
        {jobs.data?.running ? (
          <Table<any>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={jobs.data.jobs}
            columns={[
              { title: "Задача", dataIndex: "name" },
              { title: "Следующий запуск", dataIndex: "next_run", render: dt },
            ]}
          />
        ) : (
          <Typography.Text type="secondary">Планировщик работает отдельным процессом (floraplan scheduler) или отключён.</Typography.Text>
        )}
      </Card>
      <div className="toolbar">
        <Select placeholder="Все системы" allowClear style={{ width: 220 }} value={system} onChange={setSystem} options={Object.entries(SYS).map(([k, v]) => ({ value: k, label: v }))} />
        <span className="spacer" />
        {can("analyst") && (
          <Space>
            <Button loading={busy} onClick={async () => (await run(() => api.post("/api/onec/import-folder"), "Папка обмена обработана")) && log.reload()}>
              Загрузить чеки из папки обмена
            </Button>
          </Space>
        )}
      </div>
      <Table<any>
        rowKey="id"
        size="small"
        loading={log.loading}
        dataSource={log.data || []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 800 }}
        columns={[
          { title: "Время", dataIndex: "ts", width: 150, render: dt },
          { title: "Система", dataIndex: "system", width: 160, render: (v) => SYS[v] || v },
          { title: "", dataIndex: "direction", width: 70, render: (v) => (v === "out" ? "выгрузка" : "загрузка") },
          { title: "Статус", dataIndex: "status", width: 90, render: (v) => <Tag color={{ ok: "green", warn: "orange", error: "red" }[v as string]}>{v}</Tag> },
          { title: "Сообщение", dataIndex: "message" },
        ]}
      />
    </>
  );
}

function Backups() {
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/admin/backups"));
  const { busy, run } = useAction();
  return (
    <>
      <div className="toolbar">
        <Button type="primary" loading={busy} onClick={async () => (await run(() => api.post("/api/admin/backups"), "Резервная копия создана")) && reload()}>
          Создать резервную копию
        </Button>
        <Typography.Text type="secondary">Копия создаётся и ежедневно в 02:00; хранятся последние 14.</Typography.Text>
      </div>
      <Table<any>
        rowKey="name"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={false}
        columns={[
          { title: "Файл", dataIndex: "name" },
          { title: "Создан", dataIndex: "created", render: dt },
          { title: "Размер, МБ", dataIndex: "size", align: "right", render: (v) => (v / 1048576).toFixed(1) },
          { title: "", width: 60, render: (_, b) => <Button size="small" icon={<DownloadOutlined />} onClick={() => download(`/api/admin/backups/${encodeURIComponent(b.name)}`)} /> },
        ]}
      />
    </>
  );
}
