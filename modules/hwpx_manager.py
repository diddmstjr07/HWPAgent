import html
import logging
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree


class HwpxManager:
    """Manage HWPX XML mapping, HTML rendering, and text injection."""

    def __init__(self) -> None:
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._base_dir: Optional[Path] = None
        self._owns_base_dir = False
        self._section_trees: List[Tuple[Path, etree._ElementTree]] = []
        self._section_tree_map: Dict[str, etree._ElementTree] = {}
        self._id_to_node: Dict[str, etree._Element] = {}
        self._node_to_id: Dict[etree._Element, str] = {}
        self._id_to_path: Dict[str, Dict[str, str]] = {}
        self._logger = logging.getLogger(__name__)

    def load_and_map(self, hwpx_path: str, extract_dir: Optional[str] = None) -> Dict[str, etree._Element]:
        """Unzip hwpx and map text nodes to UUIDs."""
        self._cleanup()
        self._logger.info("Opening HWPX file at %s...", hwpx_path)
        if extract_dir:
            self._base_dir = Path(extract_dir)
            if self._base_dir.exists():
                shutil.rmtree(self._base_dir)
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._owns_base_dir = False
        else:
            self._temp_dir = tempfile.TemporaryDirectory()
            self._base_dir = Path(self._temp_dir.name)
            self._owns_base_dir = True

        hwpx_file = Path(hwpx_path)
        if not hwpx_file.exists():
            raise FileNotFoundError(hwpx_path)

        with zipfile.ZipFile(hwpx_file, "r") as zf:
            zf.extractall(self._base_dir)

        contents_dir = self._base_dir / "Contents"
        if not contents_dir.exists():
            raise FileNotFoundError("Contents directory not found in HWPX")

        section_paths = sorted(contents_dir.glob("section*.xml"))
        if not section_paths:
            raise FileNotFoundError("No section*.xml files found in Contents/")

        self._section_trees = []
        self._section_tree_map = {}
        self._id_to_node = {}
        self._node_to_id = {}
        self._id_to_path = {}

        parser = etree.XMLParser(remove_blank_text=False)
        total_paragraphs = 0
        total_text_nodes = 0
        sample_count = 0
        for section_path in section_paths:
            self._logger.info("Parsing section XML: %s", section_path.name)
            tree = etree.parse(str(section_path), parser)
            self._section_trees.append((section_path, tree))
            rel_path = section_path.relative_to(self._base_dir).as_posix()
            self._section_tree_map[rel_path] = tree
            para_count, text_count, samples = self._map_text_nodes(tree, rel_path)
            total_paragraphs += para_count
            total_text_nodes += text_count
            for node_id, snippet in samples:
                if sample_count >= 3:
                    break
                self._logger.debug('Mapped: %s -> "%s..."', node_id, snippet)
                sample_count += 1

        self._logger.info(
            "Mapping Complete: Found %d paragraphs, Assigned IDs to %d text nodes.",
            total_paragraphs,
            total_text_nodes,
        )
        return dict(self._id_to_node)

    def load_from_extracted(self, base_dir: str, mapping: Dict[str, Dict[str, str]]) -> None:
        """Load extracted HWPX tree and mapping from disk."""
        self._cleanup()
        self._base_dir = Path(base_dir)
        if not self._base_dir.exists():
            raise FileNotFoundError(base_dir)
        self._owns_base_dir = False
        self._id_to_path = dict(mapping or {})
        self._section_trees = []
        self._section_tree_map = {}
        self._id_to_node = {}
        self._node_to_id = {}

        parser = etree.XMLParser(remove_blank_text=False)
        section_paths = sorted({entry.get("section") for entry in self._id_to_path.values() if entry.get("section")})
        if not section_paths:
            raise FileNotFoundError("No section paths found in mapping")
        for rel_path in section_paths:
            section_path = self._base_dir / rel_path
            if not section_path.exists():
                continue
            tree = etree.parse(str(section_path), parser)
            self._section_trees.append((section_path, tree))
            self._section_tree_map[rel_path] = tree

    def generate_html_with_ids(self) -> str:
        """Render minimal HTML with data-node-id attributes."""
        if not self._section_trees:
            raise RuntimeError("load_and_map must be called first.")

        parts: List[str] = ['<div class="hwpx-doc">']
        for _, tree in self._section_trees:
            parts.append(self._render_section(tree))
        parts.append("</div>")
        return "".join(parts)

    def update_and_save(self, changes_json: List[Dict[str, str]], output_path: str) -> str:
        """Apply text updates and save a new hwpx file."""
        if not self._section_trees or not self._base_dir:
            raise RuntimeError("load_and_map or load_from_extracted must be called first.")

        for change in changes_json or []:
            node_id = str(change.get("id") or "").strip()
            if not node_id:
                continue
            new_text = change.get("text")
            node = self._resolve_node(node_id)
            if node is None:
                continue
            node.text = "" if new_text is None else str(new_text)

        for path, tree in self._section_trees:
            tree.write(
                str(path),
                encoding="utf-8",
                xml_declaration=True,
                pretty_print=False,
            )

        output_file = Path(output_path)
        if output_file.exists():
            output_file.unlink()

        with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in self._base_dir.rglob("*"):
                if file_path.is_dir():
                    continue
                rel_path = file_path.relative_to(self._base_dir).as_posix()
                zf.write(file_path, rel_path)

        return str(output_file)

    def close(self) -> None:
        """Cleanup extracted files."""
        self._cleanup()

    def _cleanup(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
        elif self._owns_base_dir and self._base_dir and self._base_dir.exists():
            shutil.rmtree(self._base_dir)
        self._temp_dir = None
        self._base_dir = None
        self._owns_base_dir = False
        self._section_trees = []
        self._section_tree_map = {}
        self._id_to_node = {}
        self._node_to_id = {}
        self._id_to_path = {}

    def export_mapping(self) -> Dict[str, Dict[str, str]]:
        return dict(self._id_to_path)

    def _map_text_nodes(self, tree: etree._ElementTree, section_rel: str) -> Tuple[int, int, List[Tuple[str, str]]]:
        root = tree.getroot()
        paragraphs = root.xpath('.//*[local-name()="p"]')
        para_count = len(paragraphs)
        text_count = 0
        samples: List[Tuple[str, str]] = []
        for para in paragraphs:
            for text_node in para.xpath('.//*[local-name()="t"]'):
                node_id = uuid.uuid4().hex
                self._id_to_node[node_id] = text_node
                self._node_to_id[text_node] = node_id
                self._id_to_path[node_id] = {
                    "section": section_rel,
                    "path": tree.getpath(text_node),
                }
                text_count += 1
                if len(samples) < 3:
                    raw_text = (text_node.text or "").strip()
                    snippet = " ".join(raw_text.split())[:20]
                    samples.append((node_id, snippet))
        return para_count, text_count, samples

    def _render_section(self, tree: etree._ElementTree) -> str:
        root = tree.getroot()
        body = self._find_first_by_local(root, "body") or root
        parts: List[str] = []
        for child in list(body):
            local = self._local_name(child.tag)
            if local == "p":
                html_block = self._render_paragraph(child)
                if html_block:
                    parts.append(html_block)
            elif local == "tbl":
                parts.append(self._render_table(child))
        if not parts:
            for para in root.xpath('.//*[local-name()="p"]'):
                html_block = self._render_paragraph(para)
                if html_block:
                    parts.append(html_block)
        return "".join(parts)

    def _render_paragraph(self, para: etree._Element) -> str:
        spans: List[str] = []
        for node in para.iter():
            if self._local_name(node.tag) != "t":
                continue
            node_id = self._node_to_id.get(node)
            if not node_id:
                continue
            text = node.text or ""
            spans.append(
                f'<span data-node-id="{node_id}">{html.escape(text)}</span>'
            )
        if not spans:
            return ""
        return f"<p>{''.join(spans)}</p>"

    def _render_table(self, table: etree._Element) -> str:
        rows_html: List[str] = []
        for row in self._find_children_by_local(table, "tr"):
            cells_html: List[str] = []
            for cell in self._find_children_by_local(row, "tc"):
                cell_parts: List[str] = []
                for para in cell.xpath('.//*[local-name()="p"]'):
                    html_block = self._render_paragraph(para)
                    if html_block:
                        cell_parts.append(html_block)
                cell_body = "".join(cell_parts) if cell_parts else "<p></p>"
                cells_html.append(f"<td>{cell_body}</td>")
            rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
        return f"<table><tbody>{''.join(rows_html)}</tbody></table>"

    def _resolve_node(self, node_id: str) -> Optional[etree._Element]:
        node = self._id_to_node.get(node_id)
        if node is not None:
            return node
        entry = self._id_to_path.get(node_id)
        if not entry:
            return None
        section_rel = entry.get("section") or ""
        path = entry.get("path") or ""
        tree = self._section_tree_map.get(section_rel)
        if not tree or not path:
            return None
        nsmap = self._build_xpath_nsmap(tree.getroot())
        try:
            result = tree.xpath(path, namespaces=nsmap)
        except Exception:
            return None
        if not result:
            return None
        node = result[0]
        self._id_to_node[node_id] = node
        return node

    @staticmethod
    def _build_xpath_nsmap(root: etree._Element) -> Dict[str, str]:
        nsmap = {key: value for key, value in (root.nsmap or {}).items() if key}
        default_ns = (root.nsmap or {}).get(None)
        if default_ns:
            nsmap.setdefault("hp", default_ns)
            nsmap.setdefault("ns0", default_ns)
        return nsmap

    def _find_first_by_local(self, root: etree._Element, name: str) -> Optional[etree._Element]:
        for elem in root.iter():
            if self._local_name(elem.tag) == name:
                return elem
        return None

    def _find_children_by_local(self, root: etree._Element, name: str) -> List[etree._Element]:
        return [child for child in list(root) if self._local_name(child.tag) == name]

    @staticmethod
    def _local_name(tag: str) -> str:
        if not tag:
            return ""
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag
