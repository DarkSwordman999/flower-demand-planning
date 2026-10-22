import { Button, Card, Descriptions, Form, Input, Typography } from "antd";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction } from "../hooks";

export default function Profile() {
  const { user } = useAuth();
  const { busy, run } = useAction();
  const [form] = Form.useForm();

  const save = async (v: any) => {
    const ok = await run(() => api.post("/api/auth/password", { old_password: v.old, new_password: v.new1 }), "Пароль изменён");
    if (ok) form.resetFields();
  };

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Профиль
      </Typography.Title>
      <Card style={{ maxWidth: 520 }}>
        <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="Пользователь">{user?.full_name}</Descriptions.Item>
          <Descriptions.Item label="Логин">{user?.login}</Descriptions.Item>
          <Descriptions.Item label="Роль">{user?.role_name}</Descriptions.Item>
        </Descriptions>
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item name="old" label="Текущий пароль" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="new1" label="Новый пароль" rules={[{ required: true, min: 6, message: "Не короче 6 символов" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="new2"
            label="Повторите новый пароль"
            dependencies={["new1"]}
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator: (_, v) => (v === getFieldValue("new1") ? Promise.resolve() : Promise.reject(new Error("Пароли не совпадают"))),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>
            Сменить пароль
          </Button>
        </Form>
      </Card>
    </>
  );
}
