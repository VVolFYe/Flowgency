import Link from "next/link";
import { Brand } from "@/components/brand";
import { PublicNav } from "@/components/public-nav";
import { HomeSimulation } from "@/components/home-simulation";

export default function Home() {
  return (
    <main className="home-page">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="home-header"><Brand /><PublicNav active="home" /></header>
      <section className="home-hero" id="main-content">
        <h1>Give every green<br />a reason.</h1>
        <p>See traffic move. Understand the signals.<br className="hidden sm:block" /> Explore adaptive control in a live SUMO simulation.</p>
        <div className="home-actions">
          <Link className="action-primary" href="/simulation">Explore the simulation <span aria-hidden="true">↗</span></Link>
          <Link className="action-secondary" href="/access">Open your workspace <span aria-hidden="true">→</span></Link>
        </div>
      </section>
      <section className="home-product" aria-label="Flowgency live simulation preview"><HomeSimulation /></section>
      <section className="home-story">
        <div><h2>A clearer view of<br />every intersection.</h2><p>Follow the full control loop, from camera observations to the signals on the road.</p></div>
        <div className="story-list">
          <article><h3>Observe the traffic</h3><p>Camera observations inform estimated demand. Simulated queues stay visible as their own measurement.</p></article>
          <article><h3>Compare the response</h3><p>Run fixed and adaptive control on the same scenario. Compare waiting times and completed journeys.</p></article>
          <article><h3>Make room for emergencies</h3><p>Test ambulance priority in the emergency demo, with voice alerts as traffic events unfold.</p></article>
        </div>
      </section>
      <footer className="home-footer"><Brand /><span>Built for UniHack 2026</span><Link href="/access">Analyst & operator access →</Link></footer>
    </main>
  );
}
