import { motion } from "framer-motion";
import { X } from "lucide-react";
import { EVENT_TYPE_CONFIG } from "../constants";
import type { PropertyEvent } from "../types";

interface EventDetailProps {
  event: PropertyEvent;
  onClose: () => void;
}

export function EventDetail({ event, onClose }: EventDetailProps) {
  const config =
    EVENT_TYPE_CONFIG[event.event_type] ?? EVENT_TYPE_CONFIG.permit_other;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.2 }}
      className="overflow-hidden"
    >
      <div className="mt-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded-md ${config.color}`}>
              <Icon size={14} />
            </div>
            <p className="data-label uppercase tracking-widest text-xs">
              {config.label}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-navy-700 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-0">
          {(event.description ?? null) && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">
                Description
              </p>
              <p className="text-sm text-white">{event.description}</p>
            </div>
          )}
          <div className="py-2 border-b border-navy-700/50">
            <p className="data-label uppercase tracking-widest text-xs mb-0.5">
              Date
            </p>
            <p className="text-sm text-white font-mono">
              {event.event_date
                ? new Date(event.event_date + "T00:00:00").toLocaleDateString(
                    "en-US",
                    {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    },
                  )
                : "Unknown"}
            </p>
          </div>
          {event.sale_price != null && event.sale_price > 0 && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">
                Sale Price
              </p>
              <p className="text-sm text-amber-400 font-mono font-medium">
                ${event.sale_price.toLocaleString()}
              </p>
            </div>
          )}
          {event.permit_type && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">
                Permit Type
              </p>
              <p className="text-sm text-white">{event.permit_type}</p>
            </div>
          )}
          {event.permit_valuation != null && event.permit_valuation > 0 && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">
                Valuation
              </p>
              <p className="text-sm text-white font-mono">
                ${event.permit_valuation.toLocaleString()}
              </p>
            </div>
          )}
          {event.permit_description && (
            <div className="py-2 border-b border-navy-700/50">
              <p className="data-label uppercase tracking-widest text-xs mb-0.5">
                Details
              </p>
              <p className="text-sm text-slate-300">
                {event.permit_description}
              </p>
            </div>
          )}
          <div className="py-2">
            <p className="data-label uppercase tracking-widest text-xs mb-0.5">
              Source
            </p>
            <p className="text-sm text-slate-300">
              {event.source.replaceAll("_", " ")}
            </p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
