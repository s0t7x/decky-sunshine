import { VFC, useState, useRef } from 'react'
import { Focusable, showModal } from "decky-frontend-lib";
import { FaInfoCircle } from "react-icons/fa";
import { InfoModal } from "./InfoModal";

/**
 * A field label with a small, focusable (i) button next to it. Pressing it opens
 * an InfoModal with the full explanation, so settings rows can stay compact
 * instead of carrying long inline descriptions.
 *
 * A bare Focusable doesn't get Steam's default focus ring, so we track focus
 * ourselves and visibly highlight the button when it's selected.
 */
export const LabelWithInfo: VFC<{
    title: string;
    help: string;
}> = ({ title, help }) => {
    const [focused, setFocused] = useState(false);
    const lastOpenRef = useRef(0);

    // A Focusable can deliver both onActivate and onClick for a single press, which
    // would stack two identical modals. Stop propagation (so we never toggle the
    // parent field) and de-dupe opens that land within the same interaction.
    const open = (e?: any) => {
        e?.stopPropagation?.();
        const now = performance.now();
        if (now - lastOpenRef.current < 300) return;
        lastOpenRef.current = now;
        showModal(<InfoModal title={title} body={help} />);
    };

    return (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span>{title}</span>
            <Focusable
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor: "pointer",
                    width: 26,
                    height: 26,
                    borderRadius: "50%",
                    transition: "background 0.12s ease, transform 0.12s ease",
                    background: focused ? "rgba(255, 255, 255, 0.25)" : "transparent",
                    boxShadow: focused ? "0 0 0 2px rgba(255, 255, 255, 0.7)" : "none",
                    transform: focused ? "scale(1.1)" : "scale(1)",
                }}
                onActivate={open}
                onClick={open}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onGamepadFocus={() => setFocused(true)}
                onGamepadBlur={() => setFocused(false)}
                onOKActionDescription="Show help"
            >
                <FaInfoCircle style={{ opacity: focused ? 1 : 0.6 }} />
            </Focusable>
        </div>
    );
};
