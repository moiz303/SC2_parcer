import vtk

import os


class GLBViewer:
    def __init__(self, parent, obj_path):
        self.frame = parent

        self.render_window = vtk.vtkRenderWindow()
        self.interactor = vtk.vtkRenderWindowInteractor()

        self.interactor.SetRenderWindow(self.render_window)
        self.renderer = vtk.vtkRenderer()
        self.render_window.AddRenderer(self.renderer)

        self.interactor = self.render_window.GetInteractor()
        self.load(obj_path)

        self.interactor.Initialize()
        self.render_window.Render()

    def load(self, path):
        self.importer = vtk.vtkOBJImporter()
        self.importer.SetFileName(os.path.join(str(path), 'preview.obj'))
        self.importer.SetFileNameMTL(os.path.join(str(path), 'preview.mtl'))
        self.importer.SetTexturePath(os.path.join(str(path), 'preview_textures'))

        self.importer.SetRenderWindow(self.render_window)
        self.importer.Update()

        self.renderer.ResetCamera()
        style = vtk.vtkInteractorStyleTrackballCamera()
        self.interactor.SetInteractorStyle(style)