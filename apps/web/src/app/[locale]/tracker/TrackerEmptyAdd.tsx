"use client";

import { useRouter } from "@/i18n/navigation";
import { AddApplicationEntry } from "./AddApplicationEntry";

/** The "+ Add" entry for the first-run empty tracker: after adding, navigate to
 *  the new application (which also drops us out of the empty state). */
export function TrackerEmptyAdd() {
  const router = useRouter();
  return (
    <AddApplicationEntry
      onAdded={(id) => {
        router.push(`/tracker?selected=${id}`);
        router.refresh();
      }}
    />
  );
}
