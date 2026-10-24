import { useState } from "react";
import { Button, InputNumber, Select, Table, Tabs, Tag, Typography } from "antd";
import { api } from "../api";
import { useAuth } from "../auth";
import { useAction, useLoad, useRefs, useSettings } from "../hooks";
import { BATCH_STATES, d, money, num } from "../format";
import { WriteOffModal } from "./Stock";

export default function Expiry() {
  const { user } = useAuth();
  const locs = useRefs("locations");
  const st = useSettings();
  const [loc, setLoc] = useState<number | undefined>(user?.location_id ?? undefined);
  return (
    <>
      <Typography.Title level={3} className="page-title">
        Сроки реализации и уценка
      </Typography.Title>
      <div className="toolbar">
        <Select
          placeholder="Все точки продаж"
          allowClear
          style={{ minWidth: 220 }}
          value={loc}
          onChange={setLoc}
          options={locs.filter((l) => l.type !== "warehouse").map((l) => ({ value: l.id, label: l.name }))}
        />
      </div>
      <Tabs
        items={[
          { key: "m", label: `Уценка (срок ≤ ${st.expiring_days} дн.)`, children: <Markdown loc={loc} /> },
          { key: "e", label: "Срок истёк — к списанию", children: <Expired loc={loc} /> },
        ]}
      />
    </>
  );
}

function Markdown({ loc }: { loc?: number }) {
  const { can } = useAuth();
  const st = useSettings();
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/expiry/recommendations", { location_id: loc }), [loc]);
  const [disc, setDisc] = useState<Record<number, number>>({});
  const [sel, setSel] = useState<number[]>([]);
  const [wo, setWo] = useState<any[]>([]);
  const { busy, run } = useAction();

  const apply = async () => {
    const items = sel.map((id) => {
      const r = (data || []).find((x) => x.id === id);
      return { batch_id: id, discount_pct: disc[id] ?? (r.recommended_discount || st.markdown_min) };
    });
    if (items.some((i) => !i.discount_pct)) return;
    const ok = await run(() => api.post("/api/expiry/markdown", { items }), "Уценка подтверждена — цены уйдут в кассы");
    if (ok) {
      setSel([]);
      reload();
    }
  };

  return (
    <>
      {can("florist", "storekeeper") && (
        <div className="toolbar">
          {can("florist") && (
            <Button type="primary" disabled={!sel.length} loading={busy} onClick={apply}>
              Уценить выбранные ({sel.length})
            </Button>
          )}
          <Button danger disabled={!sel.length} onClick={() => setWo((data || []).filter((x) => sel.includes(x.id)))}>
            Списать — утрачен товарный вид
          </Button>
        </div>
      )}
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        scroll={{ x: 1000 }}
        pagination={false}
        rowSelection={can("florist", "storekeeper") ? { selectedRowKeys: sel, onChange: (k) => setSel(k as number[]) } : undefined}
        columns={[
          { title: "Партия", dataIndex: "id", width: 75 },
          { title: "Товар", dataIndex: "product" },
          { title: "Точка", dataIndex: "location", width: 170 },
          { title: "Годен до", dataIndex: "expiry_date", width: 100, render: d },
          { title: "Дней", dataIndex: "days_left", width: 60, align: "right" },
          { title: "Остаток", dataIndex: "available", width: 80, align: "right", render: (v) => num(v) },
          { title: "Продастся по прогнозу", dataIndex: "forecast_sales", width: 110, align: "right", render: (v) => num(v) },
          { title: "Не продастся", dataIndex: "unsold", width: 100, align: "right", render: (v) => (v > 0 ? <b>{num(v)}</b> : "0") },
          { title: "Цена", dataIndex: "sale_price", width: 90, align: "right", render: money },
          {
            title: "Скидка, %",
            width: 120,
            render: (_, r) =>
              r.recommendation === "уценить" || sel.includes(r.id) ? (
                <InputNumber min={st.markdown_min} max={st.markdown_max} step={5} value={disc[r.id] ?? (r.recommended_discount || st.markdown_min)} onChange={(v) => setDisc((s) => ({ ...s, [r.id]: Number(v) }))} />
              ) : r.discount_pct ? (
                `${r.discount_pct}`
              ) : (
                "—"
              ),
          },
          {
            title: "Рекомендация",
            dataIndex: "recommendation",
            width: 170,
            render: (v, r) => <Tag color={v === "уценить" ? "orange" : v === "уценка уже действует" ? BATCH_STATES.marked_down[1] : "green"}>{v === "уценить" ? `уценить на ${r.recommended_discount}%` : v}</Tag>,
          },
        ]}
      />
      <WriteOffModal
        open={wo.length > 0}
        batches={wo}
        onClose={(ok) => {
          setWo([]);
          if (ok) {
            setSel([]);
            reload();
          }
        }}
      />
    </>
  );
}

function Expired({ loc }: { loc?: number }) {
  const { can } = useAuth();
  const { data, loading, reload } = useLoad<any[]>(() => api.get("/api/expiry/expired", { location_id: loc }), [loc]);
  const [sel, setSel] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  return (
    <>
      {can("florist", "storekeeper") && (
        <div className="toolbar">
          <Button danger disabled={!sel.length} onClick={() => setOpen(true)}>
            Списать выбранные ({sel.length})
          </Button>
        </div>
      )}
      <Table<any>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data || []}
        pagination={false}
        scroll={{ x: 800 }}
        rowSelection={can("florist", "storekeeper") ? { selectedRowKeys: sel.map((x) => x.id), onChange: (_, rows) => setSel(rows) } : undefined}
        columns={[
          { title: "Партия", dataIndex: "id", width: 80 },
          { title: "Товар", dataIndex: "product" },
          { title: "Место", dataIndex: "location" },
          { title: "Годен до", dataIndex: "expiry_date", render: d },
          { title: "Остаток", dataIndex: "available", align: "right", render: (v) => num(v) },
          { title: "Себестоимость", dataIndex: "cost", align: "right", render: money },
        ]}
      />
      <WriteOffModal
        open={open}
        batches={sel}
        onClose={(ok) => {
          setOpen(false);
          if (ok) {
            setSel([]);
            reload();
          }
        }}
      />
    </>
  );
}
