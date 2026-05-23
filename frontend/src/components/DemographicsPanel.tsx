import { motion } from "framer-motion";
import { useDemographicsQuery, usePropertyEventsQuery } from "../hooks/queries";
import { useAppStore } from "../store";
import { HousingChart } from "./demographics/HousingChart";
import { IncomeValueChart } from "./demographics/IncomeValueChart";
import { NeighborhoodSnapshot } from "./demographics/NeighborhoodSnapshot";
import { PopulationChart } from "./demographics/PopulationChart";
import { PriceHistoryChart } from "./demographics/PriceHistoryChart";
import { UnsupportedCountyBanner } from "./demographics/UnsupportedCountyBanner";

interface DemographicsPanelProps {
  parcelId: string;
  enabled: boolean;
  compact?: boolean;
}

export function DemographicsPanel({
  parcelId,
  enabled,
  compact,
}: DemographicsPanelProps) {
  const selectedYear = useAppStore((s) => s.selectedYear);
  const {
    data: demographics,
    isLoading: demographicsLoading,
    isError: demoFailed,
    error: demoError,
  } = useDemographicsQuery(parcelId, enabled);
  const {
    data: propertyEvents,
    isError: eventsFailed,
    error: eventsError,
  } = usePropertyEventsQuery(parcelId, enabled);

  if (demographicsLoading) {
    return (
      <div className="flex flex-col gap-3 p-4 animate-pulse">
        <div className="h-3 w-32 bg-navy-800 rounded" />
        <div className="h-32 bg-navy-800/50 rounded-lg" />
        <div className="h-32 bg-navy-800/50 rounded-lg" />
      </div>
    );
  }

  const hasDemo = demographics && demographics.snapshots.length > 0;
  const hasPropertyData = propertyEvents && propertyEvents.events.length > 0;
  const showUnsupported = propertyEvents && !propertyEvents.supported;

  if (demoFailed && eventsFailed) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-xs text-red-400">
        <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
        <span>Could not load demographics or property data</span>
      </div>
    );
  }

  if (
    !hasDemo &&
    !hasPropertyData &&
    !showUnsupported &&
    !demoFailed &&
    !eventsFailed
  ) {
    return (
      <div className="flex items-center justify-center p-6 text-center">
        <p className="text-xs text-slate-500">
          No census or property data available yet.
          <br />
          Data will appear once the timeline finishes processing.
        </p>
      </div>
    );
  }

  const snapshots = demographics?.snapshots ?? [];
  const subtitles = demographics?.subtitles ?? [];
  const notes = demographics?.notes;

  const popSubtitle = subtitles.find((s) =>
    s.toLowerCase().includes("population"),
  );
  const valueSubtitle = subtitles.find((s) =>
    s.toLowerCase().includes("home value"),
  );
  const ownerSubtitle = subtitles.find((s) =>
    s.toLowerCase().includes("owner"),
  );

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto scrollbar-thin scrollbar-thumb-navy-700 scrollbar-track-transparent">
      {demoFailed && !eventsFailed && (
        <div className="flex items-center gap-2 text-xs text-red-400">
          <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
          <span>
            Could not load demographics: {demoError?.message ?? "unknown error"}
          </span>
        </div>
      )}
      {eventsFailed && !demoFailed && (
        <div className="flex items-center gap-2 text-xs text-red-400">
          <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
          <span>
            Could not load property data:{" "}
            {eventsError?.message ?? "unknown error"}
          </span>
        </div>
      )}
      {subtitles.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-wrap gap-2"
        >
          {subtitles.slice(0, 3).map((s) => (
            <span
              key={s}
              className="text-[10px] text-amber-400/70 bg-amber-400/5 border border-amber-400/10 rounded-full px-2.5 py-0.5"
            >
              {s}
            </span>
          ))}
        </motion.div>
      )}

      {hasPropertyData && propertyEvents && (
        <PriceHistoryChart
          propertyEvents={propertyEvents}
          selectedYear={selectedYear}
        />
      )}

      {showUnsupported && !hasPropertyData && (
        <UnsupportedCountyBanner county={propertyEvents?.county ?? null} />
      )}

      {hasDemo && (
        <>
          <PopulationChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={popSubtitle}
          />

          <HousingChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={ownerSubtitle}
          />

          <IncomeValueChart
            snapshots={snapshots}
            selectedYear={selectedYear}
            subtitle={valueSubtitle}
            compact={compact}
          />

          <NeighborhoodSnapshot snapshots={snapshots} />
        </>
      )}

      {notes && (
        <p className="text-[9px] text-slate-600 leading-relaxed mt-1">
          {notes}
        </p>
      )}
    </div>
  );
}
