import { VFC } from 'react'
import { ModalRoot } from "decky-frontend-lib";

/**
 * A minimal read-only modal that shows a title and a block of explanatory text.
 * Used by the little (i) help buttons next to settings so the panel itself can
 * stay compact instead of carrying long inline descriptions.
 */
export const InfoModal: VFC<{
    closeModal?: () => void;
    title: string;
    body: string;
}> = ({ closeModal, title, body }) => {
    return (
        <ModalRoot onCancel={closeModal} onEscKeypress={closeModal}>
            <h2 style={{ margin: "0 0 0.5em 0" }}>{title}</h2>
            <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4, opacity: 0.9 }}>
                {body}
            </div>
        </ModalRoot>
    );
};
