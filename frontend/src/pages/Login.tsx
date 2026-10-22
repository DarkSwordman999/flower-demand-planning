import { useState } from "react";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (v: { login: string; password: string }) => {
    setBusy(true);
    setError("");
    try {
      await login(v.login, v.password);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <Card style={{ width: 380, maxWidth: "100%" }}>
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <img src="/favicon.svg" width={56} height={56} alt="" />
          <Typography.Title level={3} style={{ margin: "8px 0 0" }}>
            ФлораПлан
          </Typography.Title>
          <Typography.Text type="secondary">Планирование закупок и продаж цветочной продукции</Typography.Text>
        </div>
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="login" label="Логин" rules={[{ required: true, message: "Введите логин" }]}>
            <Input prefix={<UserOutlined />} autoFocus autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="Пароль" rules={[{ required: true, message: "Введите пароль" }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy} size="large">
            Войти
          </Button>
        </Form>
      </Card>
    </div>
  );
}
