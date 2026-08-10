"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, forceX, forceY } from "d3-force";
import { drag } from "d3-drag";
import { pointer, select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import { api } from "../../lib/api";

type Person = {
  id: string;
  name: string;
  category?: string;
  health_score?: number;
  betweenness?: number;
  community_id?: string | number;
  company?: string;
  occupation?: string;
  last_contacted?: string;
  birthday?: string;
  anniversary?: string;
  contact_frequency_days?: number;
  streak_weeks?: number;
  email?: string;
  phone?: string;
  profile_notes?: string;
  topics_of_interest?: string[];
  [key: string]: any;
};
type Edge = { id?: string; person_a_id: string; person_b_id: string; strength?: string; label?: string; weight?: number };
type SimNode = Person & { x?: number; y?: number; fx?: number | null; fy?: number | null; isCenter?: boolean; _radius?: number };

const CATEGORIES = ["FAMILY", "FRIENDS", "IMPORTANT", "COUSINS", "RELATIVES", "COLLEAGUES", "NEW_CONTACT", "NETWORK"];
const CATEGORY_COLORS: Record<string, string> = {
  FAMILY: "#fb7185", FRIENDS: "#f59e0b", IMPORTANT: "#facc15", COUSINS: "#c084fc",
  RELATIVES: "#e879f9", COLLEAGUES: "#2dd4bf", NEW_CONTACT: "#60a5fa", NETWORK: "#94a3b8",
};
const CATEGORY_LABELS: Record<string, string> = {
  FAMILY: "Family", FRIENDS: "Friends", IMPORTANT: "Important", COUSINS: "Cousins",
  RELATIVES: "Relatives", COLLEAGUES: "Colleagues", NEW_CONTACT: "New contact", NETWORK: "Network",
};

function health(score?: number) {
  if (score === undefined || score === null) return { label: "No signal", color: "#94a3b8" };
  if (score >= 0.8) return { label: "Healthy", color: "#22c55e" };
  if (score >= 0.4) return { label: "Drifting", color: "#f59e0b" };
  return { label: "Needs attention", color: "#ef4444" };
}

function daysSince(date?: string) {
  if (!date) return null;
  return Math.max(0, Math.floor((Date.now() - new Date(date).getTime()) / 86400000));
}

function shapePath(category: string, x: number, y: number, r: number) {
  const sides = category === "FRIENDS" ? 3 : category === "COUSINS" ? 4 : category === "RELATIVES" ? 5 : category === "COLLEAGUES" ? 6 : 0;
  if (!sides) return `M ${x - r} ${y} a ${r} ${r} 0 1 0 ${r * 2} 0 a ${r} ${r} 0 1 0 ${-r * 2} 0`;
  const points = Array.from({ length: sides }, (_, i) => {
    const a = -Math.PI / 2 + i * (Math.PI * 2 / sides);
    return `${x + Math.cos(a) * r} ${y + Math.sin(a) * r}`;
  });
  return `M ${points.join(" L ")} Z`;
}

export default function Graph() {
  const [nodes, setNodes] = useState<Person[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Person | null>(null);
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; person: Person; connections: number } | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [showLabels, setShowLabels] = useState(true);
  const [showLegend, setShowLegend] = useState(true);
  const [error, setError] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    Promise.all([
      api<{ nodes: Person[]; edges: Edge[] }>("/relationship/graph", { limit: 300 }),
      api<Record<string, any>>("/relationship/stats"),
    ]).then(([graph, networkStats]) => {
      setNodes(graph.nodes ?? []);
      setEdges(graph.edges ?? []);
      setStats(networkStats);
    }).catch((e: any) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return nodes.filter((p) => {
      if (hidden.has(p.category ?? "NETWORK")) return false;
      return !q || [p.name, p.company, p.occupation, p.category].some((v) => String(v ?? "").toLowerCase().includes(q));
    });
  }, [nodes, query, hidden]);

  const visibleIds = useMemo(() => new Set(filtered.map((p) => p.id)), [filtered]);
  const filteredEdges = useMemo(() => edges.filter((e) => visibleIds.has(e.person_a_id) && visibleIds.has(e.person_b_id)), [edges, visibleIds]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl || !filtered.length) return;
    const W = svgEl.clientWidth || window.innerWidth;
    const H = svgEl.clientHeight || window.innerHeight;
    const svg = select(svgEl);
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${W} ${H}`);
    const root = svg.append("g");
    const center: SimNode = { id: "center", name: "YOU", category: "CENTER", isCenter: true, fx: W / 2, fy: H / 2 };
    const simNodes: SimNode[] = [center, ...filtered.map((p) => ({ ...p }))];
    const simLinks: any[] = filteredEdges.map((e) => ({ ...e, source: e.person_a_id, target: e.person_b_id }));
    simNodes.slice(1).forEach((p) => simLinks.push({ source: "center", target: p.id, weight: 0.25, isCenterLink: true }));
    const adjacent = new Map<string, Set<string>>();
    filteredEdges.forEach((e) => { adjacent.set(e.person_a_id, (adjacent.get(e.person_a_id) ?? new Set()).add(e.person_b_id)); adjacent.set(e.person_b_id, (adjacent.get(e.person_b_id) ?? new Set()).add(e.person_a_id)); });
    const simulation = forceSimulation(simNodes)
      .force("link", forceLink<any, any>(simLinks).id((d: SimNode) => d.id).distance((d: any) => d.isCenterLink ? 170 : 105).strength((d: any) => d.isCenterLink ? 0.08 : 0.42))
      .force("charge", forceManyBody().strength(-240).distanceMax(750))
      .force("center", forceCenter(W / 2, H / 2))
      .force("radial", forceRadial((d: SimNode) => d.isCenter ? 0 : 110 + (1 - (d.health_score ?? 0.5)) * 170, W / 2, H / 2).strength(0.2))
      .force("collide", forceCollide<SimNode>().radius((d) => d.isCenter ? 28 : 10 + (d.betweenness ?? 0) * 22).strength(1))
      .force("x", forceX(W / 2).strength(0.04)).force("y", forceY(H / 2).strength(0.04));
    const lines = root.append("g").selectAll("line").data(simLinks).join("line")
      .attr("stroke", (e: any) => e.isCenterLink ? "rgba(255,255,255,.07)" : (e.strength === "STRONG" ? "#c9793f" : e.strength === "WEAK" ? "#5b7c99" : "#a78bfa"))
      .attr("stroke-opacity", (e: any) => e.isCenterLink ? 0.3 : 0.65)
      .attr("stroke-width", (e: any) => e.isCenterLink ? 1 : 1.3 + (e.weight ?? 0.6) * 1.5);
    const group = root.append("g").selectAll("g.node").data(simNodes).join("g").attr("class", "node").style("cursor", "pointer");
    group.append("circle").attr("class", "halo").attr("r", (d) => d.isCenter ? 32 : 0).attr("fill", "rgba(201,121,63,.18)");
    group.append("path").attr("class", "node-shape").attr("fill", (d) => d.isCenter ? "#818cf8" : health(d.health_score).color).attr("stroke", (d) => d.isCenter ? "#c4b5fd" : CATEGORY_COLORS[d.category ?? "NETWORK"]).attr("stroke-width", 1.5);
    group.append("text").attr("class", "nlabel").attr("text-anchor", "middle").attr("y", (d) => d.isCenter ? 48 : 24).attr("fill", "rgba(255,255,255,.88)").attr("font-size", (d) => d.isCenter ? 12 : 11).attr("font-weight", (d) => d.isCenter ? 700 : 500).text((d) => d.name);
    const active = (id: string | null) => {
      const ids = id ? new Set([id, ...(adjacent.get(id) ?? [])]) : null;
      group.attr("opacity", (d: SimNode) => !ids || d.isCenter || ids.has(d.id) ? 1 : 0.13);
      lines.attr("stroke-opacity", (e: any) => !ids || e.isCenterLink || (ids.has(e.source.id ?? e.source) && ids.has(e.target.id ?? e.target)) ? 0.8 : 0.05);
    };
    group.on("mouseenter", (event, d: SimNode) => {
      if (d.isCenter) return;
      active(d.id);
      const [x, y] = pointer(event, svgEl);
      setTooltip({ x, y, person: d, connections: adjacent.get(d.id)?.size ?? 0 });
    }).on("mouseleave", () => { active(null); setTooltip(null); }).on("click", (event, d: SimNode) => {
      if (d.isCenter) return;
      event.stopPropagation();
      setSelected(d);
      api<Record<string, any>>(`/relationship/person/${d.id}`).then(setDetail).catch((e: any) => setError(e.message));
    });
    let moved = false;
    (group as any).call(drag<SVGGElement, SimNode>().on("start", (event, d) => { moved = false; if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; event.sourceEvent?.stopPropagation(); }).on("drag", (event, d) => { moved = true; d.fx = event.x; d.fy = event.y; }).on("end", (event, d) => { if (!event.active) simulation.alphaTarget(0); if (!d.isCenter) { d.fx = null; d.fy = null; } }));
    const zoomBehavior = zoom<SVGSVGElement, unknown>().scaleExtent([0.25, 6]).on("zoom", (event) => root.attr("transform", event.transform));
    zoomRef.current = zoomBehavior;
    svg.call(zoomBehavior).on("click", () => { if (!moved) { setSelected(null); setDetail(null); } });
    const draw = () => {
      lines.attr("x1", (e: any) => e.source.x).attr("y1", (e: any) => e.source.y).attr("x2", (e: any) => e.target.x).attr("y2", (e: any) => e.target.y);
      group.attr("transform", (d) => `translate(${d.x},${d.y})`);
      group.select(".node-shape").attr("d", (d: SimNode) => shapePath(d.category ?? "NETWORK", 0, 0, d.isCenter ? 16 : 6 + (d.health_score ?? 0.5) * 6));
      group.select(".nlabel").attr("opacity", (d: SimNode) => d.isCenter || showLabels ? 1 : 0);
    };
    simulation.on("tick", draw);
    setTimeout(() => svg.call(zoomBehavior.transform, zoomIdentity.translate(0, 0).scale(Math.min(1.15, Math.max(0.7, W / 900)))), 450);
    return () => { simulation.stop(); svg.on(".zoom", null); zoomRef.current = null; };
  }, [filtered, filteredEdges, showLabels]);

  const selectedConnections = selected ? filteredEdges.filter((e) => e.person_a_id === selected.id || e.person_b_id === selected.id) : [];
  const focusSelected = () => {
    if (!selected || !svgRef.current || !zoomRef.current) return;
    const svg = select(svgRef.current);
    svg.transition().duration(450).call(zoomRef.current.scaleTo, 2.5);
  };
  const toggleCategory = (category: string) => setHidden((current) => { const next = new Set(current); if (next.has(category)) next.delete(category); else next.add(category); return next; });
  const resetCamera = () => { if (svgRef.current && zoomRef.current) select(svgRef.current).transition().duration(450).call(zoomRef.current.transform, zoomIdentity); };
  const zoomBy = (factor: number) => { if (svgRef.current && zoomRef.current) select(svgRef.current).transition().duration(250).call(zoomRef.current.scaleBy, factor); };
  const selectedHealth = health(selected?.health_score);

  return <div className="graph-os">
    <div className="graph-os-topbar">
      <div className="graph-os-brand"><span className="graph-os-mark">◈</span><div><strong>Relationship OS</strong><small>your network, with context</small></div></div>
      <div className="graph-os-search"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search nodes…" /><kbd>⌘ K</kbd></div>
      <div className="graph-os-actions"><button onClick={() => zoomBy(1.35)} title="Zoom in">＋</button><button onClick={() => zoomBy(0.74)} title="Zoom out">−</button><button className={showLabels ? "on" : ""} onClick={() => setShowLabels((v) => !v)} title="Toggle labels">Aa</button><button className={showLegend ? "on" : ""} onClick={() => setShowLegend((v) => !v)} title="Toggle legend">◌</button><button onClick={resetCamera} title="Reset camera">↻</button></div>
    </div>
    {error && <div className="graph-os-error">{error}</div>}
    <div className="graph-os-stats"><span><strong>{stats.total_contacts ?? nodes.length}</strong> people</span><i /> <span><strong>{edges.length}</strong> connections</span><i /> <span><strong>{stats.interactions_this_week ?? 0}</strong> touches this week</span><i /> <span><strong>{Math.round((nodes.reduce((sum, n) => sum + (n.health_score ?? 0), 0) / Math.max(1, nodes.length)) * 100)}%</strong> avg health</span></div>
    <svg ref={svgRef} className="graph-os-canvas" aria-label="Interactive relationship graph" />
    {showLegend && <div className="graph-os-legend"><header><span>Circles</span><button onClick={() => setShowLegend(false)}>×</button></header>{CATEGORIES.map((category) => <button key={category} onClick={() => toggleCategory(category)} className={hidden.has(category) ? "hidden" : ""}><span style={{ background: CATEGORY_COLORS[category] }} />{CATEGORY_LABELS[category]}<em>{nodes.filter((n) => n.category === category).length}</em></button>)}<footer><span className="legend-health good" /> healthy <span className="legend-health warn" /> drifting <span className="legend-health bad" /> attention</footer></div>}
    <div className="graph-os-count"><strong>{filtered.length}</strong> visible · scroll to zoom · drag to arrange</div>
    {tooltip && <div className="graph-os-tooltip" style={{ left: tooltip.x + 18, top: tooltip.y + 18 }}><strong>{tooltip.person.name}</strong><span>{tooltip.person.company || CATEGORY_LABELS[tooltip.person.category ?? "NETWORK"]}</span><span style={{ color: health(tooltip.person.health_score).color }}>{health(tooltip.person.health_score).label} · {tooltip.connections} connection{tooltip.connections === 1 ? "" : "s"}</span>{tooltip.person.last_contacted && <span>Last touch {daysSince(tooltip.person.last_contacted)}d ago</span>}</div>}
    {selected && <aside className="graph-os-inspector"><button className="inspector-close" onClick={() => { setSelected(null); setDetail(null); }}>×</button><div className="inspector-hero"><div className="inspector-avatar" style={{ background: `linear-gradient(135deg, ${CATEGORY_COLORS[selected.category ?? "NETWORK"]}, ${selectedHealth.color})` }}>{selected.name.slice(0, 1)}</div><div><h2>{selected.name}</h2><p>{selected.occupation || CATEGORY_LABELS[selected.category ?? "NETWORK"]}</p></div></div><div className="inspector-actions"><button onClick={focusSelected}>◎ Focus</button><a href="/people/">↗ Profile</a></div><div className="inspector-health"><div><strong style={{ color: selectedHealth.color }}>{Math.round((selected.health_score ?? 0) * 100)}%</strong><span>relationship health</span></div><div><strong>{selected.streak_weeks ?? 0}w</strong><span>current streak</span></div><div><strong>{selectedConnections.length}</strong><span>connections</span></div></div>{selected.company && <section><h3>Work</h3><p>{selected.company}{selected.occupation ? ` · ${selected.occupation}` : ""}</p></section>}{selected.email || selected.phone ? <section><h3>Contact</h3>{selected.email && <a href={`mailto:${selected.email}`}>✉ {selected.email}</a>}{selected.phone && <a href={`tel:${selected.phone}`}>☎ {selected.phone}</a>}</section> : null}{selected.birthday || selected.anniversary ? <section><h3>Dates</h3>{selected.birthday && <p>🎂 Birthday · {new Date(selected.birthday).toLocaleDateString(undefined, { month: "long", day: "numeric" })}</p>}{selected.anniversary && <p>♥ Anniversary · {new Date(selected.anniversary).toLocaleDateString(undefined, { month: "long", day: "numeric" })}</p>}</section> : null}{selected.profile_notes && <section><h3>Notes</h3><p className="preserve-lines">{selected.profile_notes}</p></section>}{detail?.recent_interactions?.length ? <section><h3>Recent interactions</h3>{detail.recent_interactions.slice(0, 5).map((interaction: any) => <div className="inspector-event" key={interaction.id}><strong>{interaction.type}</strong><span>{interaction.summary || "Interaction logged"}</span><small>{interaction.date ? new Date(interaction.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "recent"}</small></div>)}</section> : null}<a className="inspector-meeting" href="/people/">Open full relationship card →</a></aside>}
  </div>;
}
