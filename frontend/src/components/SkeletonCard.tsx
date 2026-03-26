/**
 * SkeletonCard — shimmer loading skeleton for timeline cards and panels.
 */

interface SkeletonCardProps {
  width?: string;
  height?: string;
  className?: string;
}

export function SkeletonCard({
  width = "w-16",
  height = "h-16",
  className = "",
}: SkeletonCardProps) {
  return (
    <div
      className={`${width} ${height} rounded-md bg-navy-800 animate-pulse shrink-0 ${className}`}
    />
  );
}

export function SkeletonText({
  width = "w-24",
  className = "",
}: {
  width?: string;
  className?: string;
}) {
  return (
    <div
      className={`${width} h-3 rounded bg-navy-800 animate-pulse ${className}`}
    />
  );
}
