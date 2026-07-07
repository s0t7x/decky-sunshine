import { VFC, useState, useRef } from 'react'
import { Focusable } from "decky-frontend-lib";
import { FaInfoCircle } from "react-icons/fa";

/**
 * A field label with a small, focusable (i) button next to it. Pressing it
 * toggles the field's help text on and off, so settings rows can stay compact
 * instead of carrying long inline descriptions.
 *
 * A bare Focusable doesn't get Steam's default focus ring, so we track focus
 * ourselves and visibly highlight the button when it's selected.
 */
export const LabelWithInfo: VFC<{
    title: string;
    onToggleHelp: () => void;
}> = ({ title, onToggleHelp }) => {
    const [focused, setFocused] = useState(false);
    const lastToggleRef = useRef(0);
    const suppressFocusUntilRef = useRef(0);

    // A Focusable can deliver both onActivate and onClick for a single press, which
    // would toggle the help text right back off. Stop propagation (so we never
    // toggle the parent field) and de-dupe presses that land within the same
    // interaction.
    const toggle = (e?: any) => {
        e?.stopPropagation?.();
        const now = performance.now();
        if (now - lastToggleRef.current < 300) return;
        lastToggleRef.current = now;
        onToggleHelp();
    };

    // Touch input focuses the button and leaves it focused (the Deck fires the
    // gamepad focus events for touch as well), which would leave the highlight
    // stuck after a tap. Touch is detectable via DOM touch events though: drop
    // the highlight on touch and suppress the focus events arriving with the
    // same tap. Gamepad navigation fires no touch events, so a controller
    // keeps the highlight while the button is focused.
    const onTouch = () => {
        suppressFocusUntilRef.current = performance.now() + 500;
        setFocused(false);
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
                onActivate={toggle}
                onClick={toggle}
                onTouchEnd={onTouch}
                // Deliberately no DOM onFocus/onBlur: the highlight only exists
                // for gamepad navigation, see onTouch above.
                onGamepadFocus={() => {
                    if (performance.now() < suppressFocusUntilRef.current) return;
                    setFocused(true);
                }}
                onGamepadBlur={() => setFocused(false)}
                onOKActionDescription="Toggle help"
            >
                <FaInfoCircle style={{ opacity: focused ? 1 : 0.6 }} />
            </Focusable>
        </div>
    );
};
