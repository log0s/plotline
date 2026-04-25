import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import {
  motion,
  animate,
  type MotionValue,
} from "framer-motion";

type SnapPoint = "closed" | "half" | "full";

const HANDLE_HEIGHT = 44;

interface MobileBottomSheetProps {
  children: ReactNode;
  expandTrigger?: unknown;
  y: MotionValue<number>;
  resetKey?: string;
}

export function MobileBottomSheet({
  children,
  expandTrigger,
  y,
  resetKey,
}: MobileBottomSheetProps) {
  const [snap, setSnap] = useState<SnapPoint>("closed");
  const sheetRef = useRef<HTMLDivElement>(null);
  const [sheetHeight, setSheetHeight] = useState(0);
  const animRef = useRef<ReturnType<typeof animate> | null>(null);
  const measuredRef = useRef(false);
  const prevTrigger = useRef(expandTrigger);
  const openedByTrigger = useRef(false);
  const preTriggerSnap = useRef<SnapPoint>("closed");
  const prevResetKey = useRef(resetKey);

  useEffect(() => {
    const el = sheetRef.current;
    if (!el) return;
    const update = () => setSheetHeight(el.offsetHeight);
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const getSnapY = useCallback(
    (s: SnapPoint) => {
      if (sheetHeight <= 0)
        return s === "full" ? 0 : s === "half" ? 300 : 600;
      switch (s) {
        case "full":
          return 0;
        case "half":
          return Math.round(sheetHeight * 0.5);
        case "closed":
          return sheetHeight - HANDLE_HEIGHT;
      }
    },
    [sheetHeight],
  );

  useEffect(() => {
    if (sheetHeight <= 0) return;
    const target = getSnapY(snap);
    if (!measuredRef.current) {
      measuredRef.current = true;
      y.set(target);
    } else {
      animRef.current?.stop();
      animRef.current = animate(y, target, {
        type: "spring",
        damping: 30,
        stiffness: 300,
      });
    }
  }, [snap, sheetHeight, getSnapY, y]);

  useEffect(() => {
    if (expandTrigger != null && expandTrigger !== prevTrigger.current && snap !== "full") {
      preTriggerSnap.current = snap;
      openedByTrigger.current = true;
      setSnap("full");
    } else if (expandTrigger == null && prevTrigger.current != null && openedByTrigger.current) {
      openedByTrigger.current = false;
      setSnap(preTriggerSnap.current);
    }
    prevTrigger.current = expandTrigger;
  }, [expandTrigger, snap]);

  useEffect(() => {
    if (resetKey !== prevResetKey.current) {
      prevResetKey.current = resetKey;
      openedByTrigger.current = false;
      preTriggerSnap.current = "closed";
      setSnap("closed");
    }
  }, [resetKey]);

  const dragState = useRef({
    startY: 0,
    startMotionY: 0,
    startTime: 0,
    active: false,
  });

  const onPointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    animRef.current?.stop();
    dragState.current = {
      startY: e.clientY,
      startMotionY: y.get(),
      startTime: Date.now(),
      active: true,
    };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragState.current.active) return;
    const delta = e.clientY - dragState.current.startY;
    const newY = dragState.current.startMotionY + delta;
    y.set(Math.max(getSnapY("full"), Math.min(getSnapY("closed"), newY)));
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!dragState.current.active) return;
    dragState.current.active = false;

    const delta = e.clientY - dragState.current.startY;
    const dt = Math.max(1, Date.now() - dragState.current.startTime);
    const velocity = (delta / dt) * 1000;
    const endY = y.get();

    openedByTrigger.current = false;

    if (velocity < -500) {
      if (snap === "closed") setSnap("half");
      else setSnap("full");
    } else if (velocity > 500) {
      if (snap === "full") setSnap("half");
      else setSnap("closed");
    } else {
      const points: SnapPoint[] = ["full", "half", "closed"];
      const nearest = points.reduce((a, b) =>
        Math.abs(endY - getSnapY(a)) < Math.abs(endY - getSnapY(b)) ? a : b,
      );
      setSnap(nearest);
    }
  };

  return (
    <motion.div
      ref={sheetRef}
      className="absolute bottom-0 left-0 right-0 z-20 bg-navy-900/95 backdrop-blur-md rounded-t-2xl border-t border-navy-700/60 shadow-2xl shadow-black/50 flex flex-col"
      style={{ height: "min(85%, calc(100% - 60px))", y }}
    >
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className="flex justify-center py-3 cursor-grab active:cursor-grabbing shrink-0"
        style={{ touchAction: "none" }}
      >
        <div className="w-10 h-1.5 rounded-full bg-slate-500" />
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 overscroll-contain">
        {children}
      </div>
    </motion.div>
  );
}
