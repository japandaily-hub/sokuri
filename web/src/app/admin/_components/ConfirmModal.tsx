"use client";

/**
 * r8-fix-frontend: 依頼者・業者ページでも再利用できるよう components/kdz/ConfirmModal.tsx に
 * 移動した。admin 配下の既存 import（`from "./_components/ConfirmModal"`）を壊さないよう、
 * ここは再エクスポートのみ行う互換シムとして残す。
 */
export { ConfirmModal } from "@/components/kdz/ConfirmModal";
