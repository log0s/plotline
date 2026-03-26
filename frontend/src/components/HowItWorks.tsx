/**
 * HowItWorks — three-step explainer section on the landing page.
 */
import { motion } from "framer-motion";
import { BarChart3, Layers, Search } from "lucide-react";

const steps = [
  {
    icon: Search,
    title: "Search any address",
    description: "Enter a US street address and we geocode it instantly.",
  },
  {
    icon: Layers,
    title: "Explore the timeline",
    description:
      "Browse decades of aerial and satellite imagery from NAIP, Landsat, and Sentinel-2.",
  },
  {
    icon: BarChart3,
    title: "Discover the story",
    description:
      "See census demographics, property sales, and building permits that shaped the land.",
  },
];

export function HowItWorks() {
  return (
    <section className="w-full max-w-4xl mx-auto px-4 py-16">
      <h2 className="text-sm font-medium uppercase tracking-widest text-slate-500 text-center mb-10">
        How it works
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {steps.map((step, i) => (
          <motion.div
            key={step.title}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-50px" }}
            transition={{ delay: i * 0.12, duration: 0.4 }}
            className="flex flex-col items-center text-center"
          >
            <div className="w-12 h-12 rounded-2xl bg-navy-800 border border-navy-700/60 flex items-center justify-center mb-4">
              <step.icon className="w-5 h-5 text-amber-400" />
            </div>
            <h3 className="text-white font-medium mb-2">{step.title}</h3>
            <p className="text-sm text-slate-400 leading-relaxed">
              {step.description}
            </p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
