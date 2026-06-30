import { X, AlertCircle, CheckCircle2 } from "lucide-react";
import type { ValidarHorarioResponse } from "../types";

const TIPO_LABEL: Record<string, string> = {
  INTRA: "Solapamiento interno",
  NRC: "Componentes solapados",
  RD1: "Tope de malla",
  RD2: "Fuera de disponibilidad del profesor",
  RD3: "Profesor en dos lados a la vez",
  RD4: "Sala especial sin capacidad",
  RD7: "Ayudantía antes de las 12:30",
};

export default function ValidacionPanel({
  resultado,
  onClose,
  onJumpToSeccion,
}: {
  resultado: ValidarHorarioResponse;
  onClose: () => void;
  onJumpToSeccion?: (secId: string) => void;
}) {
  return (
    <div
      className="fixed top-20 right-6 w-80 max-h-[75vh] overflow-y-auto z-40
                     bg-white border border-gray-200 rounded-lg shadow-lg"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 sticky top-0 bg-white">
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
          Restricciones del horario actual
        </h3>
        <button onClick={onClose}>
          <X size={14} className="text-gray-400 hover:text-gray-600" />
        </button>
      </div>

      <div className="p-4 space-y-3">
        <div
          className={`flex items-center gap-2 px-3 py-2 rounded text-xs font-medium
          ${
            resultado.factible
              ? "bg-green-50 text-green-700 border border-green-200"
              : "bg-red-50 text-red-700 border border-red-200"
          }`}
        >
          {resultado.factible ? (
            <CheckCircle2 size={13} />
          ) : (
            <AlertCircle size={13} />
          )}
          {resultado.factible
            ? "Sin violaciones de restricciones duras"
            : `${resultado.violaciones_duras.length} violación(es) dura(s)`}
        </div>

        <div className="text-xs text-gray-500">
          Penalización blanda:{" "}
          <span className="font-semibold text-gray-800">
            {resultado.penalizacion_blanda.toFixed(0)}
          </span>
        </div>

        {resultado.violaciones_duras.length > 0 && (
          <ul className="space-y-2">
            {resultado.violaciones_duras.map((v, i) => (
              <li
                key={i}
                className="border border-red-200 rounded p-2.5 bg-red-50/40"
              >
                <span className="text-[10px] font-bold bg-red-200 text-red-800 px-1.5 py-0.5 rounded">
                  {v.tipo}
                </span>
                <span className="ml-1.5 text-[11px] text-red-700 font-medium">
                  {TIPO_LABEL[v.tipo] ?? v.tipo}
                </span>
                <p className="text-xs text-gray-700 mt-1 leading-relaxed">
                  {v.mensaje}
                </p>
                {v.secciones.length > 0 && onJumpToSeccion && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {v.secciones.map((secId) => (
                      <button
                        key={secId}
                        onClick={() => onJumpToSeccion(secId)}
                        className="text-[10px] bg-white border border-gray-200 rounded px-1.5 py-0.5
                                   text-gray-600 hover:border-gray-400"
                      >
                        {secId}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
