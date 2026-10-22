import { useState } from "react";
import { Alert, Button, Card, DatePicker, Select, Table, Tag, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import dayjs, { type Dayjs } from "dayjs";
import { api, download } from "../api";
import { useLoad, useRefs } from "../hooks";
import { iso, num } from "../format";

const KINDS: Record<string, { name: string; groups: [string, string][]; chart?: string; days: number }> = {
  sales: { name: "Продажи и маржа", groups: [["group", "по группам"], ["product", "по товарам"], ["location", "по точкам"], ["day", "по дням"], ["week", "по неделям"], ["month", "по месяцам"]], chart: "revenue", days: 30 },
  writeoffs: { name: "Списания", groups: [["reason", "по причинам"], ["group", "по группам"], ["product", "по товарам"], ["location", "по местам"], ["week", "по неделям"]], chart: "cost", days: 30 },
  turnover: { name: "Оборачиваемость", groups: [["product", "по товарам"], ["group", "по группам"], ["location", "по местам"]], chart: "turnover_days", days: 30 },
  accuracy: { name: "Точность прогноза", groups: [["group", "по группам"], ["product", "по товарам"], ["week", "по неделям"]], chart: "wape_pct", days: 28 },
  abcxyz: { name: "ABC/XYZ-анализ", groups: [], days: 90 },
  purchases: { name: "Закупки", groups: [["supplier", "по поставщикам"], ["status", "по статусам"]], chart: "sum", days: 30 },
};

export default function Reports() {
  const locs = useRefs("locations");
  const [kind, setKind] = useState("sales");
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, "day"), dayjs()]);
  const [gb, setGb] = useState<string>("group");
  const [loc, setLoc] = useState<number | undefined>();
  const params = { date_from: iso(range[0]), date_to: iso(range[1]), group_by: gb, location_id: loc };
  const { data, loading } = useLoad<any>(() => api.get(`/api/reports/${kind}`, params), [kind, range, gb, loc]);
  const k = KINDS[kind];

  const pick = (v: string) => {
    setKind(v);
    setGb(KINDS[v].groups[0]?.[0] || "");
    setRange([dayjs().subtract(KINDS[v].days - 1, "day"), dayjs()]);
  };

  const columns = (data?.columns || []).map((c: any, i: number) => ({
    title: c.title,
    dataIndex: c.key,
    align: i === 0 || ["group", "abc", "xyz", "class"].includes(c.key) ? ("left" as const) : ("right" as const),
    render: (v: any) =>
      ["abc", "xyz", "class"].includes(c.key) ? (
        <Tag color={{ A: "green", X: "green", B: "blue", Y: "blue", C: "default", Z: "orange" }[String(v)[0]]}>{v}</Tag>
      ) : typeof v === "number" ? (
        num(v, 2)
      ) : (
        v ?? "—"
      ),
    sorter: i > 0 ? (a: any, b: any) => (a[c.key] ?? -1e18) - (b[c.key] ?? -1e18) : undefined,
  }));

  return (
    <>
      <Typography.Title level={3} className="page-title">
        Отчёты
      </Typography.Title>
      <div className="toolbar">
        <Select style={{ width: 220 }} value={kind} onChange={pick} options={Object.entries(KINDS).map(([v, x]) => ({ value: v, label: x.name }))} />
        <DatePicker.RangePicker value={range} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])} format="DD.MM.YYYY" />
        {k.groups.length > 0 && <Select style={{ width: 170 }} value={gb} onChange={setGb} options={k.groups.map(([v, l]) => ({ value: v, label: l }))} />}
        {kind !== "purchases" && (
          <Select placeholder="Все места" allowClear style={{ minWidth: 200 }} value={loc} onChange={setLoc} options={locs.map((l) => ({ value: l.id, label: l.name }))} />
        )}
        <span className="spacer" />
        <Button icon={<DownloadOutlined />} onClick={() => download(`/api/reports/${kind}/xlsx`, params)}>
          Выгрузить в XLSX
        </Button>
      </div>
      {data?.note && <Alert type="info" showIcon message={data.note} style={{ marginBottom: 12 }} />}
      {k.chart && data?.rows?.length > 0 && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={data.rows.slice(0, 20)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="key" interval={0} angle={-20} textAnchor="end" height={70} tick={{ fontSize: 11 }} />
              <YAxis width={80} tickFormatter={(v) => num(v, 0)} />
              <Tooltip formatter={(v: number) => num(v, 2)} />
              <Bar dataKey={k.chart} name={data.columns.find((c: any) => c.key === k.chart)?.title} fill="#2f7a4f" />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}
      <Table<any>
        rowKey={(r) => r.key}
        size="small"
        loading={loading}
        dataSource={data?.rows || []}
        columns={columns}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 800 }}
        summary={() =>
          data?.totals && Object.keys(data.totals).length > 0 ? (
            <Table.Summary.Row>
              {(data.columns || []).map((c: any, i: number) => (
                <Table.Summary.Cell key={c.key} index={i} align={i === 0 ? "left" : "right"}>
                  <b>{typeof data.totals[c.key] === "number" ? num(data.totals[c.key], 2) : data.totals[c.key] ?? ""}</b>
                </Table.Summary.Cell>
              ))}
            </Table.Summary.Row>
          ) : null
        }
      />
    </>
  );
}
