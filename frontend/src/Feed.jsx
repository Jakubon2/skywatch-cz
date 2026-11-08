// "Mapa" tab: the event feed will live here (phase 3 feed).
export default function Feed() {
  return (
    <>
      <h2 className="section-title">Co se teď děje nad Českem</h2>
      <div className="empty">
        <div className="empty__icon">✈︎</div>
        <p className="empty__title">Zatím klid</p>
        <p>Jakmile se nad Českem stane něco zajímavého, uvidíš to tady i s vysvětlením.</p>
      </div>
    </>
  );
}
